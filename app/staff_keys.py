"""Creates or replaces staff keys from the command line (run by YOU, the owner).

  python -m app.staff_keys list                       shows companies and how many active staff keys each has
  python -m app.staff_keys new smile-dental           adds a key for one company
  python -m app.staff_keys new --all --replace        a NEW key for EVERY company, old keys switched off

The new key is shown ONCE on screen. Only a fingerprint is stored in the database,
so nobody (including me) can read it back later. Copy it somewhere safe straight away.
"""
import argparse
import os
import secrets
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.models import AuditLog, Company, StaffKey
from app.security import hash_key


def new_raw_key() -> str:
    return "stf_" + secrets.token_urlsafe(32)


def issue_key(db: Session, company: Company, label: str = "staff", replace: bool = False):
    """Returns (raw_key, number_of_old_keys_switched_off). Commits."""
    retired = 0
    if replace:
        result = db.execute(
            update(StaffKey)
            .where(StaffKey.company_id == company.id, StaffKey.is_active.is_(True))
            .values(is_active=False)
        )
        retired = result.rowcount
    raw = new_raw_key()
    key = StaffKey(company_id=company.id, key_hash=hash_key(raw), label=label)
    db.add(key)
    db.flush()
    db.add(AuditLog(
        company_id=company.id, actor_type="owner", actor_label="command line",
        action="staff_key.issue", target_type="staff_key", target_id=key.id,
        details={"label": label, "old_keys_switched_off": retired},
    ))
    db.commit()
    return raw, retired


def company_rows(db: Session):
    rows = []
    for company in db.scalars(select(Company).order_by(Company.id)):
        active = db.scalars(
            select(StaffKey).where(StaffKey.company_id == company.id, StaffKey.is_active.is_(True))
        ).all()
        rows.append((company, len(active)))
    return rows


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    new = sub.add_parser("new")
    new.add_argument("slug", nargs="?", help="company slug, for example smile-dental")
    new.add_argument("--all", action="store_true", help="every active company")
    new.add_argument("--replace", action="store_true", help="switch off the company's old staff keys")
    new.add_argument("--label", default="staff")
    args = parser.parse_args(argv)

    url = os.getenv("ADMIN_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL is missing in .env")
        return 2
    engine = create_engine(url)
    with Session(engine) as db:
        if args.command == "list":
            for company, active in company_rows(db):
                print(f"  {company.slug:<20} {company.name:<28} active staff keys: {active}")
            return 0

        if bool(args.slug) == bool(args.all):
            print("Give ONE company slug, or --all (not both). Run 'list' to see the slugs.")
            return 2
        if args.all:
            companies = list(db.scalars(select(Company).where(Company.is_active.is_(True)).order_by(Company.id)))
        else:
            company = db.scalar(select(Company).where(Company.slug == args.slug))
            if company is None:
                print(f"No company with slug '{args.slug}'. Run 'list' to see the slugs.")
                return 1
            companies = [company]
        if not companies:
            print("No companies found.")
            return 1

        print("NEW STAFF KEYS (shown once, copy them now):\n")
        for company in companies:
            raw, retired = issue_key(db, company, args.label, args.replace)
            print(f"  {company.slug}")
            print(f"    key: {raw}")
            print(f"    old keys switched off: {retired}\n")
        print("Anyone holding an old key that was switched off now gets 401 'Invalid API key'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
