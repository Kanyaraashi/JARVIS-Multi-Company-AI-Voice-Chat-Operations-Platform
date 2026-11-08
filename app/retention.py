"""Privacy tools: delete old call content, and erase one customer on request (Step 31).

    python -m app.retention clean --days 90 --dry-run     shows what would be cleaned
    python -m app.retention clean --days 90               scrubs transcripts older than 90 days
    python -m app.retention erase smile-dental +919876543210

Old calls keep their date, length, outcome and speed numbers (so reports still work) but lose the
transcript, tools list and caller number. Erasing a customer removes their name, phone, email and the
text of their tickets, notes, appointment reasons and call transcripts. Invoices are kept, because
accounting law usually requires it.
Run by YOU as the owner (it uses ADMIN_DATABASE_URL or DATABASE_URL).
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.models import Appointment, AuditLog, CallRecord, Company, Customer, SupportTicket, TicketUpdate
from app.voice.config import normalize_number

ERASED = "[erased]"


def clean_calls(db: Session, days: int, now: datetime, dry_run: bool = False) -> int:
    cutoff = now - timedelta(days=days)
    rows = db.execute(select(CallRecord.id, CallRecord.transcript, CallRecord.tools_used, CallRecord.caller_phone)
                      .where(CallRecord.started_at < cutoff)).all()
    ids = [r.id for r in rows if r.transcript or r.tools_used or r.caller_phone]
    if ids and not dry_run:
        db.execute(update(CallRecord).where(CallRecord.id.in_(ids))
                   .values(transcript=[], tools_used=[], caller_phone=None))
        db.commit()
    return len(ids)


def erase_customer(db: Session, company: Company, phone: str) -> dict:
    customer = db.scalar(select(Customer).where(Customer.company_id == company.id,
                                                Customer.phone == normalize_number(phone)))
    if customer is None:
        raise LookupError("No customer with that phone number in this company.")
    cid, comp = customer.id, company.id
    ticket_ids = list(db.scalars(select(SupportTicket.id).where(
        SupportTicket.company_id == comp, SupportTicket.customer_id == cid)))
    n_tickets = db.execute(update(SupportTicket).where(SupportTicket.id.in_(ticket_ids))
                           .values(subject=ERASED, description=ERASED)).rowcount if ticket_ids else 0
    if ticket_ids:
        db.execute(update(TicketUpdate).where(TicketUpdate.company_id == comp, TicketUpdate.ticket_id.in_(ticket_ids))
                   .values(note=None))
    n_appts = db.execute(update(Appointment).where(Appointment.company_id == comp, Appointment.customer_id == cid)
                         .values(reason=ERASED)).rowcount
    n_calls = db.execute(update(CallRecord).where(CallRecord.company_id == comp, CallRecord.customer_id == cid)
                         .values(transcript=[], tools_used=[], caller_phone=None)).rowcount
    customer.full_name, customer.email, customer.phone = "Erased customer", None, f"erased-{cid}"
    db.add(AuditLog(company_id=comp, actor_type="owner", actor_label="command line", action="customer.erase",
                    target_type="customer", target_id=cid, details={"tickets": n_tickets, "calls": n_calls}))
    db.commit()
    return {"customer_id": cid, "tickets": n_tickets, "appointments": n_appts, "calls": n_calls}


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("clean"); c.add_argument("--days", type=int, required=True); c.add_argument("--dry-run", action="store_true")
    e = sub.add_parser("erase"); e.add_argument("slug"); e.add_argument("phone")
    args = parser.parse_args(argv)
    url = os.getenv("ADMIN_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL is missing in .env"); return 2
    with Session(create_engine(url)) as db:
        if args.command == "clean":
            if args.days < 7:
                print("Refusing to clean calls newer than 7 days. Use --days 7 or more."); return 2
            n = clean_calls(db, args.days, datetime.now(timezone.utc), args.dry_run)
            print(f"{'Would clean' if args.dry_run else 'Cleaned'} {n} call record(s) older than {args.days} days.")
            return 0
        company = db.scalar(select(Company).where(Company.slug == args.slug))
        if company is None:
            print(f"No company with slug '{args.slug}'."); return 1
        try:
            result = erase_customer(db, company, args.phone)
        except LookupError as exc:
            print(exc); return 1
        print(f"Erased customer #{result['customer_id']}: {result['tickets']} ticket(s), "
              f"{result['appointments']} appointment(s), {result['calls']} call(s) scrubbed. Invoices kept.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
