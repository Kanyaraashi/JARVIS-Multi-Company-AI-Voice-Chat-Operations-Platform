"""The same request sent twice must never create a second record."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import Appointment, Customer, SupportTicket, WorkflowEvent
from conftest import new_key


def count(model, **where):
    with SessionLocal() as db:
        return db.query(model).filter_by(**where).count()


def test_ticket_repeated_with_same_key_creates_one(client, world, h, n8n):
    key = new_key()
    body = {"subject": "Billing question", "description": "Charged twice", "priority": "high"}
    first = client.post("/tickets", json=body, headers=h("dental", **{"Idempotency-Key": key}))
    second = client.post("/tickets", json=body, headers=h("dental", **{"Idempotency-Key": key}))
    assert first.json()["already_existed"] is False
    assert second.json()["already_existed"] is True
    assert first.json()["ticket"]["id"] == second.json()["ticket"]["id"]
    assert count(SupportTicket) == 1
    assert count(WorkflowEvent) == 1  # and only ONE email event
    assert len(n8n.calls) == 1


def test_same_key_in_two_companies_is_two_tickets(client, world, h, n8n):
    key = new_key()
    body = {"subject": "Hello there", "description": "Same key, other company"}
    a = client.post("/tickets", json=body, headers=h("dental", **{"Idempotency-Key": key}))
    b = client.post("/tickets", json=body, headers=h("shop", **{"Idempotency-Key": key}))
    assert a.json()["ticket"]["id"] != b.json()["ticket"]["id"]
    assert count(SupportTicket) == 2


def test_idempotency_key_is_required(client, world, h):
    r = client.post("/tickets", json={"subject": "Hello", "description": "No key"}, headers=h("dental"))
    assert r.status_code == 422


def test_ticket_validation(client, world, h, n8n):
    r = client.post("/tickets", json={"subject": "x", "description": "y"},
                    headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert r.status_code == 422
    r = client.post("/tickets", json={"subject": "Valid subject", "description": "Valid text",
                                      "priority": "banana"},
                    headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert r.status_code == 422


def test_ticket_for_unknown_customer_is_404(client, world, h, n8n):
    r = client.post("/tickets", json={"subject": "Hello", "description": "Who am I",
                                      "customer_phone": "+910000000000"},
                    headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert r.status_code == 404


def test_appointment_repeated_with_same_key_creates_one(client, world, h, n8n, day):
    key = new_key()
    body = {"customer_phone": "+919000000001", "date": day(), "time": "10:00:00"}
    first = client.post("/appointments", json=body, headers=h("dental", **{"Idempotency-Key": key}))
    second = client.post("/appointments", json=body, headers=h("dental", **{"Idempotency-Key": key}))
    assert first.status_code == second.status_code == 200
    assert second.json()["already_existed"] is True
    assert first.json()["appointment"]["id"] == second.json()["appointment"]["id"]
    assert count(Appointment) == 1
    assert len(n8n.calls) == 1  # one confirmation email, not two


def test_escalation_repeated_with_same_key_creates_one(client, world, h, n8n):
    key = new_key()
    body = {"reason": "Customer wants a callback", "customer_phone": "+919000000001"}
    first = client.post("/escalations", json=body, headers=h("dental", **{"Idempotency-Key": key}))
    second = client.post("/escalations", json=body, headers=h("dental", **{"Idempotency-Key": key}))
    assert second.json()["already_existed"] is True
    assert first.json()["ticket"]["id"] == second.json()["ticket"]["id"]
    assert first.json()["ticket"]["priority"] == "urgent"
    assert count(SupportTicket) == 1
    assert len(n8n.calls) == 1


def test_escalation_without_customer_is_allowed(client, world, h, n8n):
    r = client.post("/escalations", json={"reason": "Unknown caller needs help"},
                    headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert r.status_code == 200
    assert r.json()["ticket"]["customer_id"] is None


def test_escalation_unknown_customer_is_404(client, world, h, n8n):
    r = client.post("/escalations", json={"reason": "Help", "customer_phone": "+910000000000"},
                    headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert r.status_code == 404


def test_escalation_reports_business_hours(client, world, h, n8n, monkeypatch):
    monkeypatch.setattr("app.escalations.is_open_now", lambda company: True)
    r = client.post("/escalations", json={"reason": "Call me please"},
                    headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert r.json()["within_business_hours"] is True
    monkeypatch.setattr("app.escalations.is_open_now", lambda company: False)
    r = client.post("/escalations", json={"reason": "Call me later"},
                    headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert r.json()["within_business_hours"] is False


def test_is_open_now_follows_the_clock(world, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app import escalations
    from app.models import Company

    tz = ZoneInfo("Asia/Kolkata")

    class Fixed(datetime):
        value = None

        @classmethod
        def now(cls, tz=None):
            return cls.value

    monkeypatch.setattr(escalations, "datetime", Fixed)
    company = Company(timezone="Asia/Kolkata")
    Fixed.value = datetime(2030, 1, 7, 10, 0, tzinfo=tz)   # a Monday, 10:00
    assert escalations.is_open_now(company) is True
    Fixed.value = datetime(2030, 1, 7, 20, 0, tzinfo=tz)   # Monday evening
    assert escalations.is_open_now(company) is False
    Fixed.value = datetime(2030, 1, 6, 10, 0, tzinfo=tz)   # a Sunday
    assert escalations.is_open_now(company) is False


def test_registration_repeated_creates_one_customer(client, world, h):
    body = {"full_name": "New Person", "phone": "+91 98765 11111", "email": "new@example.com"}
    first = client.post("/customers", json=body, headers=h("dental"))
    second = client.post("/customers", json=body, headers=h("dental"))
    assert first.json()["already_existed"] is False
    assert second.json()["already_existed"] is True
    assert first.json()["customer"]["phone"] == "+919876511111"  # spaces removed
    assert count(Customer, phone="+919876511111") == 1


@pytest.mark.parametrize("body", [
    {"full_name": "Bad Phone", "phone": "12345678"},          # too short for a real number
    {"full_name": "Letters", "phone": "abcdefghijk"},
    {"full_name": "Bad Mail", "phone": "+919876500000", "email": "not-an-email"},
    {"full_name": "A", "phone": "+919876500001"},             # name too short
])
def test_registration_rejects_bad_input(client, world, h, body):
    assert client.post("/customers", json=body, headers=h("dental")).status_code == 422


def test_registration_in_other_company_with_same_phone_is_separate(client, world, h):
    r = client.post("/customers", json={"full_name": "Dev Again", "phone": "+919876543210"},
                    headers=h("shop"))
    assert r.status_code == 200 and r.json()["already_existed"] is False


def test_database_blocks_duplicate_phone_in_one_company(world):
    with SessionLocal() as db:
        with pytest.raises(IntegrityError):
            db.execute(text(
                "INSERT INTO customers (company_id, full_name, phone)"
                " VALUES (:c, 'Dup', '+919000000001')"), {"c": world["dental_id"]})
            db.commit()
