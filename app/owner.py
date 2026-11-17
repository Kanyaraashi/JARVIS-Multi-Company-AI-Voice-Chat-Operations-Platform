"""The platform owner's tool: create companies, set limits, add the first login (Step 32).
You run this on your own machine or server. Customers never can.

  python -m app.owner company-new <slug> "<Name>" --agent Maya [--timezone Asia/Kolkata] [--cap 600]
  python -m app.owner cap <slug> <minutes|none>          monthly call-minute limit (none = unlimited)
  python -m app.owner user-new <slug> <email> "<Full name>" --role owner|manager|agent   (asks for the password)
  python -m app.owner overview                           every company: minutes used, cap, calls, open tickets
  python -m app.owner company-off <slug> | company-on <slug>
  python -m app.owner hours <slug> [--open 9] [--close 18] [--slot 30] [--closed sun|sat,sun|none] [--timezone Asia/Kolkata] [--staff-email x@y.com]
  python -m app.owner text <slug> [--greeting "..."] [--instructions "..."]
  python -m app.owner faq-add <slug> "<question>" "<answer>"
  python -m app.owner faq-import <slug> faqs.csv [--check]        columns: question, answer
  python -m app.owner faq-list <slug>
  python -m app.owner customers-import <slug> people.csv [--country-code +91] [--check]    columns: full_name, phone, email
  python -m app.owner ai-key-new <slug> [--replace]               a new AI key (the old ones stop working with --replace)
  python -m app.owner onboard company.json [--check]              creates a whole company from one file (see COMPANY_ONBOARDING.md)

company-new also prints a fresh AI key and staff key ONCE. Put the AI key in .env as JARVIS_KEY_<SLUG> for the voice worker.
"""
import argparse
import getpass
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.accounts import hash_password, password_problem
from app import owner_setup as setup
from app.models import ApiKey, AuditLog, Company, Faq, StaffKey, StaffUser, SupportTicket
from app.security import hash_key
from app.usage import usage_for

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def log(db, company, action, details=None):
    db.add(AuditLog(company_id=company.id, actor_type="owner", actor_label="owner command", action=action,
                    target_type="company", target_id=company.id, details=details))


def find(db, slug):
    company = db.scalar(select(Company).where(Company.slug == slug))
    if company is None:
        raise SystemExit(f"No company with slug '{slug}'.")
    return company


def new_company(db, slug, name, agent, tz, cap):
    if not SLUG.match(slug):
        raise SystemExit("Slug: 2-49 characters, lower case letters, digits and dashes (for example smile-dental).")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise SystemExit(f"Unknown time zone '{tz}'. Example: Asia/Kolkata")
    if db.scalar(select(Company).where(Company.slug == slug)):
        raise SystemExit(f"Company '{slug}' already exists.")
    company = Company(slug=slug, name=name, agent_name=agent, timezone=tz, monthly_minutes_cap=cap,
                      greeting=f"Hello, thank you for calling {name}. This is {agent}. How can I help you today?",
                      instructions=f"You are {agent}, the phone assistant of {name}. Be warm, brief and honest. "
                                   f"If you do not know something, say so and offer a callback from a person.")
    db.add(company)
    db.flush()
    ai, staff = "jrv_" + secrets.token_urlsafe(32), "stf_" + secrets.token_urlsafe(32)
    db.add_all([ApiKey(company_id=company.id, key_hash=hash_key(ai), label="voice agent"),
                StaffKey(company_id=company.id, key_hash=hash_key(staff), label="first staff key")])
    log(db, company, "company.create", {"cap": cap})
    db.commit()
    return ai, staff


SETUP_COMMANDS = {"hours", "text", "faq-add", "faq-import", "faq-list", "customers-import", "ai-key-new", "onboard"}
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def env_name(slug):
    return "JARVIS_KEY_" + slug.upper().replace("-", "_")


def run_setup(db, args):
    """The setup commands. Each one prints what it did. SetupError (a plain message) is handled by main()."""
    if args.cmd == "onboard":
        plan = setup.read_onboarding(args.file)
        if not SLUG.match(plan["slug"]):
            raise setup.SetupError("Slug: 2-49 characters, lower case letters, digits and dashes (for example smile-dental).")
        if db.scalar(select(Company).where(Company.slug == plan["slug"])):
            raise setup.SetupError(f"Company '{plan['slug']}' already exists. Use hours, text, faq-import or customers-import to change it.")
        print(f"File is fine: {plan['name']} ({plan['slug']}), {len(plan['faqs'])} FAQ(s).")
        if args.check:
            print("Nothing was created (--check)."); return
        ai, staff = new_company(db, plan["slug"], plan["name"], plan["agent"], plan["timezone"], plan["cap"])
        company = find(db, plan["slug"])
        h = plan["hours"]
        setup.set_hours(db, company, h["open_hour"], h["close_hour"], h["slot"], h["closed"], None, h["staff_email"])
        if plan["greeting"] or plan["instructions"]:
            setup.set_text(db, company, plan["greeting"], plan["instructions"])
        added, _ = setup.add_faqs(db, company, plan["faqs"])
        print(f"Created {plan['slug']} with {added} FAQ(s). These keys are shown ONCE, save them now:\n"
              f"  AI key (voice worker and chat): {ai}\n  staff key:                      {staff}")
        print(f"Next: add {env_name(plan['slug'])}={ai} to .env, then the steps in COMPANY_ONBOARDING.md (login, QR, phone, restart).")
        return
    company = find(db, args.slug)
    if args.cmd == "hours":
        closed = None if args.closed is None else setup.parse_days(args.closed)
        setup.set_hours(db, company, args.open_hour, args.close_hour, args.slot, closed, args.timezone, args.staff_email)
        days = ", ".join(DAY_NAMES[d] for d in (company.closed_weekdays or [])) or "none"
        print(f"{args.slug}: open {company.open_hour}:00 to {company.close_hour}:00, {company.slot_minutes}-minute slots, closed: {days}, time zone {company.timezone}.")
    elif args.cmd == "text":
        setup.set_text(db, company, args.greeting, args.instructions)
        print(f"{args.slug}: updated. New calls and chats use it straight away.")
    elif args.cmd == "faq-add":
        added, skipped = setup.add_faqs(db, company, [(args.question, args.answer)])
        print(f"{args.slug}: added." if added else f"{args.slug}: that question is already there, nothing changed.")
    elif args.cmd == "faq-import":
        added, skipped = setup.import_faqs_csv(db, company, args.file, args.check)
        print(f"{args.slug}: {'would add' if args.check else 'added'} {added}, already there {skipped}." + (" Nothing was written (--check)." if args.check else ""))
    elif args.cmd == "faq-list":
        faqs = db.scalars(select(Faq).where(Faq.company_id == company.id).order_by(Faq.id)).all()
        print(f"{args.slug}: {len(faqs)} FAQ(s)")
        for f in faqs:
            print(f"  [{f.id}] {f.question}\n       {f.answer[:90]}{'...' if len(f.answer) > 90 else ''}")
    elif args.cmd == "customers-import":
        r = setup.import_customers_csv(db, company, args.file, args.country_code, args.check)
        print(f"{args.slug}: {'would add' if args.check else 'added'} {r['added']}, already there {r['existing']}, rejected {len(r['bad'])}."
              + (" Nothing was written (--check)." if args.check else ""))
        for line, why in r["bad"][:20]:
            print(f"  line {line}: {why}")
        if len(r["bad"]) > 20:
            print(f"  ... and {len(r['bad']) - 20} more")
    elif args.cmd == "ai-key-new":
        raw, retired = setup.new_ai_key(db, company, args.replace)
        print(f"New AI key for {args.slug} (shown ONCE, save it now):\n  {raw}")
        print(f"Put it in .env as {env_name(args.slug)}={raw}, then run python -m app.voice.split_env and python -m app.webchat.split_env and restart the worker and the chat service.")
        if retired:
            print(f"{retired} old AI key(s) were switched off: phone and chat for {args.slug} stay down until the new key is in place.")
        else:
            print("The old AI key still works. Add --replace to switch it off once the new one is in place.")


def main(argv=None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("company-new"); c.add_argument("slug"); c.add_argument("name")
    c.add_argument("--agent", default="Maya"); c.add_argument("--timezone", default="Asia/Kolkata"); c.add_argument("--cap", type=int)
    k = sub.add_parser("cap"); k.add_argument("slug"); k.add_argument("minutes")
    u = sub.add_parser("user-new"); u.add_argument("slug"); u.add_argument("email"); u.add_argument("name")
    u.add_argument("--role", choices=["owner", "manager", "agent"], default="owner"); u.add_argument("--password", help="avoid: it stays in your shell history; leave out to be asked")
    sub.add_parser("overview")
    h = sub.add_parser("hours"); h.add_argument("slug"); h.add_argument("--open", type=int, dest="open_hour")
    h.add_argument("--close", type=int, dest="close_hour"); h.add_argument("--slot", type=int); h.add_argument("--closed")
    h.add_argument("--timezone"); h.add_argument("--staff-email", dest="staff_email")
    t = sub.add_parser("text"); t.add_argument("slug"); t.add_argument("--greeting"); t.add_argument("--instructions")
    fa = sub.add_parser("faq-add"); fa.add_argument("slug"); fa.add_argument("question"); fa.add_argument("answer")
    fi = sub.add_parser("faq-import"); fi.add_argument("slug"); fi.add_argument("file"); fi.add_argument("--check", action="store_true")
    sub.add_parser("faq-list").add_argument("slug")
    ci = sub.add_parser("customers-import"); ci.add_argument("slug"); ci.add_argument("file")
    ci.add_argument("--country-code", default="+91"); ci.add_argument("--check", action="store_true")
    ak = sub.add_parser("ai-key-new"); ak.add_argument("slug"); ak.add_argument("--replace", action="store_true")
    ob = sub.add_parser("onboard"); ob.add_argument("file"); ob.add_argument("--check", action="store_true")
    for name in ("company-off", "company-on"):
        sub.add_parser(name).add_argument("slug")
    args = ap.parse_args(argv)

    url = os.getenv("ADMIN_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL is missing in .env"); return 2
    with Session(create_engine(url)) as db:
        try:
            if args.cmd == "company-new":
                ai, staff = new_company(db, args.slug, args.name, args.agent, args.timezone, args.cap)
                print(f"Created {args.slug}. These keys are shown ONCE, save them now:\n  AI key (voice worker): {ai}\n  staff key:             {staff}")
                print(f"Next: add JARVIS_KEY_{args.slug.upper().replace('-', '_')}={ai} to .env, add the phone number to VOICE_NUMBERS,"
                      f" then add FAQs and a first login (user-new).")
            elif args.cmd == "cap":
                company = find(db, args.slug)
                cap = None if args.minutes.lower() in ("none", "unlimited") else int(args.minutes)
                if cap is not None and cap < 0:
                    raise SystemExit("The cap cannot be negative.")
                before, company.monthly_minutes_cap = company.monthly_minutes_cap, cap
                log(db, company, "company.cap", {"before": before, "after": cap}); db.commit()
                print(f"{args.slug}: monthly cap is now {'unlimited' if cap is None else str(cap) + ' minutes'}.")
            elif args.cmd == "user-new":
                company = find(db, args.slug)
                if not EMAIL.match(args.email):
                    raise SystemExit("That email address does not look right.")
                password = args.password or getpass.getpass("Password (at least 10 characters): ")
                problem = password_problem(password)
                if problem:
                    raise SystemExit(problem)
                email = args.email.strip().lower()
                if db.scalar(select(StaffUser.id).where(StaffUser.company_id == company.id, StaffUser.email == email)):
                    raise SystemExit("That email already has a login in this company.")
                user = StaffUser(company_id=company.id, email=email, full_name=args.name, role=args.role,
                                 password_hash=hash_password(password))
                db.add(user); db.flush()
                log(db, company, "staff_user.create", {"email": email, "role": args.role}); db.commit()
                print(f"Login created for {email} ({args.role}) in {args.slug}. Sign in on /dashboard with company '{args.slug}'.")
            elif args.cmd == "overview":
                now = datetime.now(timezone.utc)
                print(f"{'company':20} {'on':3} {'minutes':>9} {'cap':>8} {'calls':>6} {'open tickets':>13}")
                for company in db.scalars(select(Company).order_by(Company.slug)):
                    use = usage_for(db, company, now)
                    open_t = db.scalar(select(func.count()).select_from(SupportTicket).where(
                        SupportTicket.company_id == company.id, SupportTicket.status.in_(("open", "in_progress"))))
                    cap = "none" if use.cap_minutes is None else f"{use.cap_minutes}"
                    flag = "" if use.allowed else "  <- OVER CAP"
                    print(f"{company.slug:20} {'yes' if company.is_active else 'NO':3} {use.used_minutes:>9} {cap:>8} {use.calls:>6} {open_t:>13}{flag}")
            elif args.cmd in SETUP_COMMANDS:
                run_setup(db, args)
            else:
                company = find(db, args.slug)
                company.is_active = args.cmd == "company-on"
                log(db, company, "company.on" if company.is_active else "company.off"); db.commit()
                print(f"{args.slug} is now {'ON' if company.is_active else 'OFF (its keys and logins stop working)'}.")
        except setup.SetupError as exc:
            db.rollback(); print(exc); return 1
        except ValueError:
            print("The cap must be a whole number of minutes, or 'none'."); return 2
        except SystemExit as exc:
            print(exc); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
