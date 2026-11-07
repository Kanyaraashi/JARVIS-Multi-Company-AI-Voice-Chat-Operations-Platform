"""One screen of numbers for a company's staff (Step 26). Read-only.

GET /staff/dashboard   (staff key)
Everything is counted for the key's own company only. "Today" follows the company's time zone.
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.latency import summarize
from app.models import Appointment, CallRecord, Company, Customer, Invoice, SupportTicket, WorkflowEvent
from app.security import get_staff_company

router = APIRouter()

OUTCOMES = ("completed", "handoff", "abandoned", "failed")
OPEN_TICKET = ("open", "in_progress")


def company_zone(company: Company) -> ZoneInfo:
    try:
        return ZoneInfo(company.timezone or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def day_bounds(now: datetime, zone: ZoneInfo):
    """Start of today and start of tomorrow in the company's time zone, as UTC moments."""
    local_midnight = datetime.combine(now.astimezone(zone).date(), time.min, tzinfo=zone)
    tomorrow = datetime.combine(local_midnight.date() + timedelta(days=1), time.min, tzinfo=zone)
    return local_midnight.astimezone(timezone.utc), tomorrow.astimezone(timezone.utc)


def _count(db: Session, *conditions) -> int:
    return db.scalar(select(func.count()).where(*conditions)) or 0


def build_dashboard(db: Session, company: Company, days: int, now: datetime) -> dict:
    cid = company.id
    zone = company_zone(company)
    start_today, start_tomorrow = day_bounds(now, zone)
    since = now - timedelta(days=days)

    # ---- tickets
    t = SupportTicket
    tickets = {
        "open": _count(db, t.company_id == cid, t.status == "open"),
        "in_progress": _count(db, t.company_id == cid, t.status == "in_progress"),
        "urgent_open": _count(db, t.company_id == cid, t.status.in_(OPEN_TICKET), t.priority == "urgent"),
        "created_today": _count(db, t.company_id == cid, t.created_at >= start_today, t.created_at < start_tomorrow),
    }

    # ---- appointments
    a = Appointment
    booked = (a.company_id == cid, a.status == "booked")
    upcoming_rows = db.execute(
        select(a, Customer.full_name)
        .outerjoin(Customer, and_(Customer.company_id == a.company_id, Customer.id == a.customer_id))
        .where(*booked, a.starts_at >= now)
        .order_by(a.starts_at)
        .limit(5)
    ).all()
    appointments = {
        "today": _count(db, *booked, a.starts_at >= start_today, a.starts_at < start_tomorrow),
        "next_7_days": _count(db, *booked, a.starts_at >= now, a.starts_at < now + timedelta(days=7)),
        "upcoming": [
            {
                "id": row.id,
                "starts_at": row.starts_at.astimezone(zone).isoformat(),
                "customer_name": name,
                "reason": row.reason,
            }
            for row, name in upcoming_rows
        ],
    }

    # ---- invoices (a company could use more than one currency, so never add them together)
    i = Invoice
    unpaid = db.execute(
        select(i.currency, func.count(), func.coalesce(func.sum(i.amount_minor), 0))
        .where(i.company_id == cid, i.status == "unpaid")
        .group_by(i.currency)
        .order_by(i.currency)
    ).all()
    invoices = {
        "unpaid_count": sum(row[1] for row in unpaid),
        "unpaid_by_currency": [
            {"currency": cur, "count": count, "total_minor": int(total)} for cur, count, total in unpaid
        ],
    }

    # ---- calls
    c = CallRecord
    by_outcome = {name: 0 for name in OUTCOMES}
    for outcome, count in db.execute(
        select(c.outcome, func.count()).where(c.company_id == cid, c.started_at >= since).group_by(c.outcome)
    ):
        by_outcome[outcome] = count
    total_calls = sum(by_outcome.values())
    turn_lists = db.scalars(
        select(c.latency_turns)
        .where(c.company_id == cid, c.started_at >= since)
        .order_by(c.id.desc())
        .limit(200)
    ).all()
    speed = summarize([turn for turns in turn_lists for turn in turns])
    calls = {
        "days": days,
        "total": total_calls,
        "today": _count(db, c.company_id == cid, c.started_at >= start_today, c.started_at < start_tomorrow),
        "by_outcome": by_outcome,
        "answered_without_trouble_pct": (
            round(100 * (by_outcome["completed"] + by_outcome["handoff"]) / total_calls) if total_calls else None
        ),
        "speed": {
            "turns": speed["turns"],
            "avg_ms": speed["avg_ms"],
            "p95_ms": speed["p95_ms"],
            "avg_llm_real_ms": speed["avg_llm_real_ms"],
            "filler_pct": speed["filler_pct"],
            "switched_pct": speed["switched_pct"],
        },
    }

    # ---- things a person should look at (only listed when there is something to look at)
    e = WorkflowEvent
    failed_events = _count(db, e.company_id == cid, e.status == "failed")
    attention = []
    if tickets["urgent_open"]:
        attention.append({"kind": "urgent_tickets", "count": tickets["urgent_open"],
                          "message": "Urgent tickets or callback requests are waiting for a person."})
    if by_outcome["failed"]:
        attention.append({"kind": "failed_calls", "count": by_outcome["failed"],
                          "message": f"Calls in the last {days} days where the AI broke down. Check /staff/calls?outcome=failed."})
    if failed_events:
        attention.append({"kind": "failed_notifications", "count": failed_events,
                          "message": "Notifications (emails or n8n workflows) that could not be sent."})

    return {
        "company": {"name": company.name, "slug": company.slug, "timezone": str(zone)},
        "generated_at": now.astimezone(zone).isoformat(),
        "tickets": tickets,
        "appointments": appointments,
        "invoices": invoices,
        "calls": calls,
        "attention": attention,
    }


@router.get("/staff/dashboard")
def dashboard(
    days: int = Query(default=7, ge=1, le=90, description="How many days of calls to summarise"),
    company: Company = Depends(get_staff_company),
    db: Session = Depends(get_db),
):
    """The numbers a staff member wants first thing in the morning."""
    return build_dashboard(db, company, days, datetime.now(timezone.utc))
