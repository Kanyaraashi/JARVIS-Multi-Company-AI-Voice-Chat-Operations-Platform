"""Owner setup commands: hours, text, FAQs, customer import, AI key replacement, one-file onboarding."""
import json

import pytest
from sqlalchemy import select

from app import owner
from app import owner_setup as setup
from app.models import ApiKey, AuditLog, Company, Customer, Faq
from conftest import AdminSession


def faqs_of(slug):
    with AdminSession() as db:
        c = db.scalar(select(Company).where(Company.slug == slug))
        if c is None:
            return []
        return [f.question for f in db.scalars(select(Faq).where(Faq.company_id == c.id).order_by(Faq.id))]


def phones_of(slug):
    with AdminSession() as db:
        c = db.scalar(select(Company).where(Company.slug == slug))
        return sorted(db.scalars(select(Customer.phone).where(Customer.company_id == c.id)))


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# ---------- hours and text ----------
def test_hours_change_only_that_company_and_are_checked(world, capsys):
    assert owner.main(["hours", "smile-dental", "--open", "8", "--close", "20", "--slot", "15", "--closed", "sat,sun"]) == 0
    assert "open 8:00 to 20:00, 15-minute slots, closed: Sat, Sun" in capsys.readouterr().out
    with AdminSession() as db:
        dental = db.scalar(select(Company).where(Company.slug == "smile-dental"))
        shop = db.scalar(select(Company).where(Company.slug == "shopeasy"))
        assert (dental.open_hour, dental.close_hour, dental.slot_minutes, dental.closed_weekdays) == (8, 20, 15, [5, 6])
        assert (shop.open_hour, shop.close_hour) == (9, 18)                       # the other company did not change
        assert db.scalar(select(AuditLog).where(AuditLog.action == "company.settings_update"))
    for bad in (["--open", "18", "--close", "9"], ["--slot", "25"], ["--closed", "funday"], ["--timezone", "Mars/Base"],
                ["--staff-email", "nope"], ["--close", "25"]):
        assert owner.main(["hours", "smile-dental"] + bad) == 1
    assert owner.main(["hours", "no-such-co", "--open", "9"]) == 1
    assert owner.main(["hours", "smile-dental", "--closed", "none"]) == 0


def test_text_updates_greeting_and_refuses_empty_or_huge(world):
    assert owner.main(["text", "smile-dental", "--greeting", "Welcome to Smile!"]) == 0
    with AdminSession() as db:
        assert db.scalar(select(Company.greeting).where(Company.slug == "smile-dental")) == "Welcome to Smile!"
        assert db.scalar(select(Company.greeting).where(Company.slug == "shopeasy")) == "Hello"
    assert owner.main(["text", "smile-dental"]) == 1
    assert owner.main(["text", "smile-dental", "--greeting", "  "]) == 1
    assert owner.main(["text", "smile-dental", "--instructions", "x" * 4001]) == 1


# ---------- FAQs ----------
def test_faq_add_skips_a_repeat_and_list_shows_only_that_company(world, capsys):
    assert owner.main(["faq-add", "smile-dental", "Do you take walk-ins?", "Yes, when a slot is free."]) == 0
    assert owner.main(["faq-add", "smile-dental", "do you take WALK-INS?", "Duplicate"]) == 0
    assert "already there" in capsys.readouterr().out.split("added.")[-1]
    assert faqs_of("smile-dental").count("Do you take walk-ins?") == 1 and "Do you take walk-ins?" not in faqs_of("shopeasy")
    capsys.readouterr()
    assert owner.main(["faq-list", "smile-dental"]) == 0
    out = capsys.readouterr().out
    assert "walk-ins" in out and "return policy" not in out
    assert owner.main(["faq-add", "smile-dental", "x", "y"]) == 1


def test_faq_import_check_writes_nothing_then_real_import_adds_and_skips(world, tmp_path, capsys):
    f = write(tmp_path, "faqs.csv", "﻿Question,Answer\nWhere are you?,12 Main Road\nWhat are your opening hours?,Already there\n")
    assert owner.main(["faq-import", "smile-dental", f, "--check"]) == 0
    assert "would add 1, already there 1" in capsys.readouterr().out and "Where are you?" not in faqs_of("smile-dental")
    assert owner.main(["faq-import", "smile-dental", f]) == 0
    assert "Where are you?" in faqs_of("smile-dental")
    assert owner.main(["faq-import", "smile-dental", f]) == 0                      # running it twice adds nothing
    assert faqs_of("smile-dental").count("Where are you?") == 1


def test_faq_import_is_all_or_nothing_and_explains_a_wrong_file(world, tmp_path, capsys):
    bad = write(tmp_path, "bad.csv", "question,answer\nGood question here,Good answer\nQ,\n")
    assert owner.main(["faq-import", "smile-dental", bad]) == 1
    assert "Good question here" not in faqs_of("smile-dental")                       # the good row was not saved either
    capsys.readouterr()
    assert owner.main(["faq-import", "smile-dental", write(tmp_path, "cols.csv", "q,a\nx,y\n")]) == 1
    assert "Missing: question, answer" in capsys.readouterr().out
    assert owner.main(["faq-import", "smile-dental", str(tmp_path / "nope.csv")]) == 1
    (tmp_path / "latin.csv").write_bytes("question,answer\nCaf\xe9?,Yes\n".encode("latin-1"))
    assert owner.main(["faq-import", "smile-dental", str(tmp_path / "latin.csv")]) == 1


# ---------- customers ----------
def test_phone_numbers_are_made_consistent():
    n = setup.normalise_phone
    assert n("98765 43210") == "+919876543210" and n("09876543210") == "+919876543210"
    assert n("+91 98765-43210") == "+919876543210" and n("0091 9876543210") == "+919876543210"
    assert n("(415) 555-0100", "+1") == "+14155550100"
    assert n("12345") is None and n("") is None and n("+0123456789") is None and n("abc") is None


def test_customer_import_adds_skips_and_reports_bad_rows_without_touching_other_companies(world, tmp_path, capsys):
    f = write(tmp_path, "people.csv",
              "full_name,phone,email\n"
              "Meera Iyer,98450 12345,Meera@Example.com\n"
              "Asha Rao,+919000000001,\n"                       # already a customer of smile-dental
              "Meera Again,9845012345,\n"                       # same number twice in the file
              "No Phone,,\n"
              "Bad Email,9811111111,not-an-email\n"
              ",9822222222,\n")
    assert owner.main(["customers-import", "smile-dental", f, "--check"]) == 0
    assert "would add 1, already there 2, rejected 3" in capsys.readouterr().out
    assert "+919845012345" not in phones_of("smile-dental")
    assert owner.main(["customers-import", "smile-dental", f]) == 0
    out = capsys.readouterr().out
    assert "added 1, already there 2, rejected 3" in out and "line 5" in out and "line 6" in out
    assert "+919845012345" in phones_of("smile-dental") and "+919845012345" not in phones_of("shopeasy")
    with AdminSession() as db:
        assert db.scalar(select(Customer.email).where(Customer.phone == "+919845012345")) == "meera@example.com"
        asha = db.scalars(select(Customer).where(Customer.phone == "+919000000001")).all()
        assert sorted(c.full_name for c in asha) == ["Asha Rao", "Dev Shop"]      # one per company, neither changed
    assert owner.main(["customers-import", "smile-dental", f]) == 0                # again: nothing new
    assert "added 0, already there 3" in capsys.readouterr().out
    assert phones_of("smile-dental").count("+919845012345") == 1


# ---------- AI key ----------
def test_ai_key_new_works_and_replace_switches_the_old_one_off(client, world, capsys):
    from conftest import KEYS
    assert client.get("/company/me", headers={"X-API-Key": KEYS["dental"]}).status_code == 200
    assert owner.main(["ai-key-new", "smile-dental"]) == 0
    out = capsys.readouterr().out
    new = next(w for w in out.split() if w.startswith("jrv_"))
    assert client.get("/company/me", headers={"X-API-Key": new}).json()["slug"] == "smile-dental"
    assert client.get("/company/me", headers={"X-API-Key": KEYS["dental"]}).status_code == 200      # old one still works
    assert owner.main(["ai-key-new", "smile-dental", "--replace"]) == 0
    newest = next(w for w in capsys.readouterr().out.split() if w.startswith("jrv_"))
    assert client.get("/company/me", headers={"X-API-Key": KEYS["dental"]}).status_code == 401
    assert client.get("/company/me", headers={"X-API-Key": new}).status_code == 401
    assert client.get("/company/me", headers={"X-API-Key": newest}).status_code == 200
    assert client.get("/company/me", headers={"X-API-Key": KEYS["shop"]}).json()["slug"] == "shopeasy"   # others untouched
    with AdminSession() as db:                                                     # only a fingerprint is stored
        assert all(newest not in k.key_hash for k in db.scalars(select(ApiKey)))
    assert owner.main(["ai-key-new", "no-such-co"]) == 1


# ---------- onboarding ----------
GOOD = {"slug": "green-clinic", "name": "Green Clinic", "agent": "Anu", "timezone": "Asia/Kolkata", "cap": 300,
        "open_hour": 10, "close_hour": 19, "slot_minutes": 20, "closed_weekdays": [6], "staff_email": "front@green.com",
        "greeting": "Hello from Green Clinic", "instructions": "Be brief.",
        "faqs": [{"question": "Where are you?", "answer": "12 Main Road"}, {"question": "Do you take cards?", "answer": "Yes"}]}


def test_onboard_creates_a_full_company_from_one_file(client, world, tmp_path, capsys):
    f = write(tmp_path, "c.json", json.dumps(GOOD))
    assert owner.main(["onboard", f, "--check"]) == 0
    assert "Nothing was created" in capsys.readouterr().out and faqs_of("green-clinic") == []
    assert owner.main(["onboard", f]) == 0
    out = capsys.readouterr().out
    ai = next(w for w in out.split() if w.startswith("jrv_"))
    assert "JARVIS_KEY_GREEN_CLINIC=" in out
    assert client.get("/company/me", headers={"X-API-Key": ai}).json()["slug"] == "green-clinic"
    with AdminSession() as db:
        c = db.scalar(select(Company).where(Company.slug == "green-clinic"))
        assert (c.agent_name, c.open_hour, c.close_hour, c.slot_minutes, c.monthly_minutes_cap) == ("Anu", 10, 19, 20, 300)
        assert c.greeting == "Hello from Green Clinic" and c.staff_email == "front@green.com"
    assert faqs_of("green-clinic") == ["Where are you?", "Do you take cards?"] and "Where are you?" not in faqs_of("smile-dental")
    assert owner.main(["onboard", f]) == 1                                         # the same company cannot be made twice


@pytest.mark.parametrize("change", [
    {"slug": "Bad Slug"}, {"slug": ""}, {"name": ""}, {"cap": -1}, {"cap": "ten"}, {"open_hour": 20, "close_hour": 9},
    {"slot_minutes": 25}, {"timezone": "Mars/Base"}, {"closed_weekdays": [7]}, {"staff_email": "nope"},
    {"faqs": [{"question": "Only a question"}]}, {"faqs": "text"}, {"greeting": ""}, {"surprise": 1},
])
def test_onboard_refuses_a_bad_file_and_creates_nothing(world, tmp_path, change):
    f = write(tmp_path, "c.json", json.dumps({**GOOD, **change}))
    assert owner.main(["onboard", f]) == 1
    with AdminSession() as db:
        assert db.scalar(select(Company).where(Company.slug.in_(["green-clinic", "Bad Slug"]))) is None


def test_onboard_explains_broken_json_and_missing_files(world, tmp_path, capsys):
    assert owner.main(["onboard", write(tmp_path, "x.json", "{not json")]) == 1
    assert "not valid JSON" in capsys.readouterr().out
    assert owner.main(["onboard", str(tmp_path / "missing.json")]) == 1
    assert owner.main(["onboard", write(tmp_path, "l.json", "[1,2]")]) == 1
