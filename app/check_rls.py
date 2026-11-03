"""Proves that row-level security works. Run: python -m app.check_rls

It connects as the API's own database user (jarvis_app) and tries to see and change
other companies' data. Every attempt must fail or show nothing.
"""
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

load_dotenv()

TABLES = [
    "companies", "faqs", "customers", "support_tickets", "api_keys", "workflow_events",
    "appointments", "staff_keys", "ticket_updates", "invoices", "audit_log", "call_records",
]
failures = 0


def check(ok: bool, text_: str) -> None:
    global failures
    print(("  PASS  " if ok else "  FAIL  ") + text_)
    if not ok:
        failures += 1


def main() -> None:
    owner_url = make_url(os.environ["DATABASE_URL"])
    password = os.environ.get("JARVIS_APP_DB_PASSWORD")
    if not password:
        sys.exit("JARVIS_APP_DB_PASSWORD is missing in .env")
    app_url = owner_url.set(username="jarvis_app", password=password)

    owner = create_engine(owner_url)
    app = create_engine(app_url)

    with owner.connect() as c:
        companies = [r[0] for r in c.execute(text("SELECT id FROM companies ORDER BY id"))]
        total = {t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in TABLES}
    print(f"Companies in the database: {companies}")
    if len(companies) < 2:
        print("  (tip: this check is strongest with two companies)")

    print("\n1. The API user is not allowed to bypass the rules")
    with app.connect() as c:
        row = c.execute(text(
            "SELECT rolsuper, rolbypassrls, rolcreatedb FROM pg_roles WHERE rolname = current_user"
        )).one()
        check(not row[0] and not row[1] and not row[2], "jarvis_app is not a superuser and cannot bypass row security")

    print("\n2. With no company selected, the API user sees nothing")
    with app.connect() as c:
        for t in TABLES:
            seen = c.execute(text(f"SELECT count(*) FROM {t}")).scalar()
            check(seen == 0, f"{t}: sees {seen} of {total[t]} rows")

    print("\n3. With company selected, it sees only that company")
    for cid in companies:
        with app.connect() as c:
            with c.begin():
                c.execute(text("SELECT set_config('app.company_id', :c, true)"), {"c": str(cid)})
                own = c.execute(text("SELECT count(*) FROM customers")).scalar()
                foreign = c.execute(text("SELECT count(*) FROM customers WHERE company_id <> :c"), {"c": cid}).scalar()
                seen_companies = c.execute(text("SELECT count(*) FROM companies")).scalar()
        check(foreign == 0 and seen_companies == 1, f"company {cid}: {own} customers, {foreign} from other companies, sees {seen_companies} company row")

    print("\n4. It cannot write into another company")
    if len(companies) >= 2:
        a, b = companies[0], companies[1]
        with app.connect() as c:
            trans = c.begin()
            c.execute(text("SELECT set_config('app.company_id', :c, true)"), {"c": str(a)})
            try:
                c.execute(text(
                    "INSERT INTO faqs (company_id, question, answer) VALUES (:b, 'rls check', 'rls check')"
                ), {"b": b})
                check(False, f"company {a} was able to insert a row for company {b}")
            except DBAPIError as exc:
                check("row-level security" in str(exc), f"company {a} cannot insert a row for company {b}")
            finally:
                trans.rollback()
        with app.connect() as c:
            with c.begin():
                c.execute(text("SELECT set_config('app.company_id', :c, true)"), {"c": str(a)})
                changed = c.execute(text("UPDATE customers SET full_name = full_name WHERE company_id = :b"), {"b": b}).rowcount
            check(changed == 0, f"company {a} changed {changed} rows of company {b}")

    print("\n5. It cannot delete or change the database structure")
    with app.connect() as c:
        for sql, label in [("DELETE FROM customers", "delete customers"),
                           ("TRUNCATE customers", "truncate customers"),
                           ("DROP TABLE faqs", "drop a table")]:
            trans = c.begin()
            try:
                c.execute(text(sql))
                check(False, f"was able to {label}")
            except DBAPIError as exc:
                check("permission denied" in str(exc) or "must be owner" in str(exc), f"cannot {label}")
            finally:
                trans.rollback()

    print()
    if failures:
        sys.exit(f"{failures} check(s) FAILED. Row-level security is not working.")
    print("All checks passed. Row-level security is working.")


if __name__ == "__main__":
    main()
