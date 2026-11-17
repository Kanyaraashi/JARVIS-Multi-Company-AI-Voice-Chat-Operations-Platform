"""Owner-side setup helpers: hours, FAQs, greeting, customer import, AI key replacement, one-file onboarding.

These are called by `python -m app.owner ...` (see the commands listed in app/owner.py). They run with the
owner's database login on your own machine, never from the internet. Every change is written to the audit log.

Every function takes an open database session and a company, changes ONLY that company, and raises
SetupError with a plain-language message when something is wrong. Nothing is changed if a check fails.
"""
import csv
import io
import json
import re
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from app.models import ApiKey, AuditLog, Customer, Faq
from app.security import hash_key

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SLOTS = (10, 15, 20, 30, 45, 60)
MAX_FAQS_PER_FILE = 500
MAX_CUSTOMERS_PER_FILE = 20000
MAX_FILE_BYTES = 5_000_000


class SetupError(Exception):
    pass


def audit(db, company, action, details=None):
    db.add(AuditLog(company_id=company.id, actor_type="owner", actor_label="owner command", action=action,
                    target_type="company", target_id=company.id, details=details))


# ---------- hours ----------
def parse_days(text: str) -> list:
    """'sun' or 'sat,sun' or 'none' -> sorted weekday numbers (0 = Monday)."""
    text = (text or "").strip().lower()
    if text in ("", "none", "no"):
        return []
    out = set()
    for part in text.split(","):
        part = part.strip()
        if part not in DAYS:
            raise SetupError(f"'{part}' is not a day. Use: mon, tue, wed, thu, fri, sat, sun (comma separated) or none.")
        out.add(DAYS.index(part))
    return sorted(out)


def set_hours(db, company, open_hour=None, close_hour=None, slot=None, closed=None, timezone=None, staff_email=None):
    new_open = company.open_hour if open_hour is None else open_hour
    new_close = company.close_hour if close_hour is None else close_hour
    if not (0 <= new_open <= 23 and 1 <= new_close <= 24) or new_open >= new_close:
        raise SetupError("Hours are whole numbers on a 24-hour clock, and opening must be before closing (for example 9 and 18).")
    if slot is not None and slot not in SLOTS:
        raise SetupError("Appointment length must be one of 10, 15, 20, 30, 45 or 60 minutes.")
    if timezone is not None:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise SetupError(f"Unknown time zone '{timezone}'. Example: Asia/Kolkata") from None
    if staff_email is not None and not EMAIL.match(staff_email):
        raise SetupError("That staff email address does not look right.")
    before = {"open_hour": company.open_hour, "close_hour": company.close_hour, "slot_minutes": company.slot_minutes,
              "closed_weekdays": list(company.closed_weekdays or []), "timezone": company.timezone}
    company.open_hour, company.close_hour = new_open, new_close
    if slot is not None:
        company.slot_minutes = slot
    if closed is not None:
        company.closed_weekdays = sorted(set(closed))
    if timezone is not None:
        company.timezone = timezone
    if staff_email is not None:
        company.staff_email = staff_email
    audit(db, company, "company.settings_update", {"before": before, "by": "owner command"})
    db.commit()


def set_text(db, company, greeting=None, instructions=None):
    if greeting is None and instructions is None:
        raise SetupError("Give --greeting and/or --instructions.")
    for label, value in (("greeting", greeting), ("instructions", instructions)):
        if value is not None and not (1 <= len(value.strip()) <= 4000):
            raise SetupError(f"The {label} must be between 1 and 4000 characters.")
    if greeting is not None:
        company.greeting = greeting.strip()
    if instructions is not None:
        company.instructions = instructions.strip()
    audit(db, company, "company.text_update", {"greeting": greeting is not None, "instructions": instructions is not None})
    db.commit()


# ---------- FAQs ----------
def clean_faq(question, answer):
    q, a = " ".join((question or "").split()), (answer or "").strip()
    if not 3 <= len(q) <= 500:
        raise SetupError(f"A question must be 3 to 500 characters: '{q[:40]}'")
    if not 2 <= len(a) <= 4000:
        raise SetupError(f"The answer to '{q[:40]}' must be 2 to 4000 characters.")
    return q, a


def add_faqs(db, company, pairs, check_only=False):
    """pairs: list of (question, answer). Returns (added, skipped_existing). A question already there is left alone."""
    if len(pairs) > MAX_FAQS_PER_FILE:
        raise SetupError(f"At most {MAX_FAQS_PER_FILE} FAQs at a time.")
    cleaned = [clean_faq(q, a) for q, a in pairs]                    # everything is checked before anything is written
    have = {f.question.strip().lower() for f in db.scalars(select(Faq).where(Faq.company_id == company.id))}
    added = skipped = 0
    for q, a in cleaned:
        if q.lower() in have:
            skipped += 1
            continue
        have.add(q.lower())
        added += 1
        if not check_only:
            db.add(Faq(company_id=company.id, question=q, answer=a))
    if added and not check_only:
        audit(db, company, "faq.import", {"added": added, "skipped": skipped})
        db.commit()
    return added, skipped


def read_csv(path, needed):
    """Reads a small CSV (UTF-8, with or without a BOM). `needed` columns must exist. Returns a list of dicts."""
    p = Path(path)
    if not p.is_file():
        raise SetupError(f"File not found: {path}")
    if p.stat().st_size > MAX_FILE_BYTES:
        raise SetupError("That file is larger than 5 MB. Split it into smaller files.")
    try:
        text = p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise SetupError("The file is not UTF-8. In Excel choose Save As, CSV UTF-8.") from None
    reader = csv.DictReader(io.StringIO(text))
    names = [(n or "").strip().lower() for n in (reader.fieldnames or [])]
    missing = [n for n in needed if n not in names]
    if missing:
        raise SetupError("The first row must have these column names: " + ", ".join(needed)
                         + ". Missing: " + ", ".join(missing))
    rows = []
    for raw in reader:
        rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k})
    return rows


def import_faqs_csv(db, company, path, check_only=False):
    rows = read_csv(path, ["question", "answer"])
    return add_faqs(db, company, [(r["question"], r["answer"]) for r in rows if r["question"] or r["answer"]], check_only)


# ---------- customers ----------
def normalise_phone(raw: str, country_code: str = "+91"):
    """Returns +<digits> or None. A plain 10-digit number gets the country code; a leading 0 is dropped."""
    digits = re.sub(r"[\s\-().]", "", raw or "")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if not digits.startswith("+"):
        digits = digits.lstrip("0")
        cc = country_code if country_code.startswith("+") else "+" + country_code
        digits = digits if len(digits) > 10 else cc + digits
        digits = digits if digits.startswith("+") else "+" + digits
    return digits if re.fullmatch(r"\+[1-9]\d{9,14}", digits) else None


def import_customers_csv(db, company, path, country_code="+91", check_only=False):
    """Columns: full_name, phone, email (email optional). Existing phones are left untouched.
    Returns dict(added, existing, bad=[(line, reason)]). With check_only nothing is written."""
    rows = read_csv(path, ["full_name", "phone"])
    if len(rows) > MAX_CUSTOMERS_PER_FILE:
        raise SetupError(f"At most {MAX_CUSTOMERS_PER_FILE} customers per file.")
    have = set(db.scalars(select(Customer.phone).where(Customer.company_id == company.id)))
    seen, bad, added, existing = set(), [], 0, 0
    for line, r in enumerate(rows, start=2):
        name = " ".join(r.get("full_name", "").split())
        phone = normalise_phone(r.get("phone", ""), country_code)
        email = (r.get("email") or "").strip().lower() or None
        if not name or len(name) > 200:
            bad.append((line, "name is empty or longer than 200 characters")); continue
        if phone is None:
            bad.append((line, f"phone '{r.get('phone', '')}' is not a valid number")); continue
        if email and (not EMAIL.match(email) or len(email) > 200):
            bad.append((line, f"email '{email}' does not look right")); continue
        if phone in have or phone in seen:
            existing += 1; continue
        seen.add(phone)
        added += 1
        if not check_only:
            db.add(Customer(company_id=company.id, full_name=name, phone=phone, email=email))
    if added and not check_only:
        audit(db, company, "customers.import", {"added": added, "already_there": existing, "rejected": len(bad)})
        db.commit()
    return {"added": added, "existing": existing, "bad": bad}


# ---------- AI key ----------
def new_ai_key(db, company, replace=False):
    """Returns (raw_key, number_switched_off). With replace, the old AI keys stop working at once."""
    retired = 0
    if replace:
        for key in db.scalars(select(ApiKey).where(ApiKey.company_id == company.id, ApiKey.is_active.is_(True))):
            key.is_active = False
            retired += 1
    raw = "jrv_" + secrets.token_urlsafe(32)
    db.add(ApiKey(company_id=company.id, key_hash=hash_key(raw), label="voice agent"))
    audit(db, company, "ai_key.issue", {"old_keys_switched_off": retired})
    db.commit()
    return raw, retired


# ---------- one-file onboarding ----------
ONBOARD_KEYS = {"slug", "name", "agent", "timezone", "cap", "open_hour", "close_hour", "slot_minutes",
                "closed_weekdays", "staff_email", "greeting", "instructions", "faqs"}


def read_onboarding(path):
    """Reads and fully checks an onboarding JSON file. Returns a clean dict. Nothing is created here."""
    p = Path(path)
    if not p.is_file():
        raise SetupError(f"File not found: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SetupError(f"The file is not valid JSON (line {exc.lineno}): {exc.msg}") from None
    if not isinstance(data, dict):
        raise SetupError("The file must hold one JSON object.")
    unknown = sorted(set(data) - ONBOARD_KEYS)
    if unknown:
        raise SetupError("Unknown field(s): " + ", ".join(unknown) + ". Allowed: " + ", ".join(sorted(ONBOARD_KEYS)))
    for need in ("slug", "name"):
        if not str(data.get(need, "")).strip():
            raise SetupError(f"'{need}' is required.")
    out = {"slug": data["slug"].strip(), "name": data["name"].strip(), "agent": (data.get("agent") or "Maya").strip(),
           "timezone": data.get("timezone", "Asia/Kolkata"), "cap": data.get("cap")}
    if out["cap"] is not None and (not isinstance(out["cap"], int) or isinstance(out["cap"], bool) or out["cap"] < 0):
        raise SetupError("'cap' must be a whole number of minutes, or left out for no limit.")
    closed = data.get("closed_weekdays")
    if closed is not None:
        if not isinstance(closed, list) or any(not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in closed):
            raise SetupError("'closed_weekdays' is a list of numbers 0 (Monday) to 6 (Sunday), for example [6].")
    out["hours"] = {"open_hour": data.get("open_hour"), "close_hour": data.get("close_hour"), "slot": data.get("slot_minutes"),
                    "closed": closed, "timezone": out["timezone"], "staff_email": data.get("staff_email")}
    h = out["hours"]
    new_open = 9 if h["open_hour"] is None else h["open_hour"]
    new_close = 18 if h["close_hour"] is None else h["close_hour"]
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (new_open, new_close)) \
            or not (0 <= new_open <= 23 and 1 <= new_close <= 24) or new_open >= new_close:
        raise SetupError("open_hour and close_hour must be whole numbers on a 24-hour clock, opening before closing.")
    if h["slot"] is not None and h["slot"] not in SLOTS:
        raise SetupError("slot_minutes must be one of 10, 15, 20, 30, 45, 60.")
    try:
        ZoneInfo(out["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        raise SetupError(f"Unknown time zone '{out['timezone']}'.") from None
    if h["staff_email"] is not None and not EMAIL.match(str(h["staff_email"])):
        raise SetupError("staff_email does not look right.")
    out["greeting"], out["instructions"] = data.get("greeting"), data.get("instructions")
    for label in ("greeting", "instructions"):
        v = out[label]
        if v is not None and (not isinstance(v, str) or not 1 <= len(v.strip()) <= 4000):
            raise SetupError(f"'{label}' must be text of 1 to 4000 characters.")
    faqs = data.get("faqs") or []
    if not isinstance(faqs, list) or any(not isinstance(f, dict) or set(f) != {"question", "answer"} for f in faqs):
        raise SetupError("'faqs' must be a list of {\"question\": ..., \"answer\": ...} objects.")
    out["faqs"] = [clean_faq(f["question"], f["answer"]) for f in faqs]
    if len(out["faqs"]) > MAX_FAQS_PER_FILE:
        raise SetupError(f"At most {MAX_FAQS_PER_FILE} FAQs in one file.")
    return out
