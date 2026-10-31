"""Shared test setup.

Safety first: these tests DELETE all rows in the database they use.
So they never touch your real database. They create and use a separate one
named <your database>_test, and refuse to run on anything not ending in _test.
"""
import os
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

# ---- 1. Point everything at a separate test database BEFORE the app is imported
_real = make_url(os.environ["DATABASE_URL"])
_test_name = (_real.database or "jarvis") + "_test"
_test = _real.set(database=_test_name)

_admin = create_engine(_real, isolation_level="AUTOCOMMIT")
with _admin.connect() as conn:
    exists = conn.execute(
        text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": _test_name}
    ).scalar()
    if not exists:
        conn.execute(text(f'CREATE DATABASE "{_test_name}"'))
_admin.dispose()

os.environ["DATABASE_URL"] = _test.render_as_string(hide_password=False)
os.environ["N8N_WEBHOOK_SECRET"] = "test-secret"
for _name in (
    "TICKET", "TICKET_UPDATED", "ESCALATION", "APPOINTMENT",
    "APPOINTMENT_CANCELLED", "APPOINTMENT_RESCHEDULED", "INVOICE",
):
    os.environ[f"N8N_{_name}_WEBHOOK_URL"] = f"http://n8n.test/webhook/{_name.lower()}"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    ApiKey, Company, Customer, Faq, Invoice, StaffKey, WorkflowEvent,
)
from app.security import hash_key  # noqa: E402

assert engine.url.database.endswith("_test"), "Refusing to run tests on a non-test database"

KEYS = {
    "dental": "jrv_dental_test_key",
    "shop": "jrv_shop_test_key",
    "dental_staff": "stf_dental_test_key",
    "shop_staff": "stf_shop_test_key",
}


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean():
    """Every test starts with empty tables."""
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def world():
    """Two companies, each with customers, an AI key, a staff key and some data."""
    with SessionLocal() as db:
        dental = Company(
            slug="smile-dental", name="Smile Dental", agent_name="Maya",
            greeting="Hi", instructions="Be kind", timezone="Asia/Kolkata",
        )
        shop = Company(
            slug="shopeasy", name="ShopEasy", agent_name="Ravi",
            greeting="Hello", instructions="Be quick", timezone="Asia/Kolkata",
        )
        db.add_all([dental, shop])
        db.flush()
        db.add_all([
            ApiKey(company_id=dental.id, key_hash=hash_key(KEYS["dental"])),
            ApiKey(company_id=shop.id, key_hash=hash_key(KEYS["shop"])),
            StaffKey(company_id=dental.id, key_hash=hash_key(KEYS["dental_staff"])),
            StaffKey(company_id=shop.id, key_hash=hash_key(KEYS["shop_staff"])),
            Faq(company_id=dental.id, question="What are your opening hours?",
                answer="Dental clinic is open 9 to 6, Monday to Saturday."),
            Faq(company_id=shop.id, question="What is your return policy?",
                answer="Shop returns are accepted within 30 days."),
        ])
        # The SAME phone number exists in both companies on purpose.
        asha = Customer(company_id=dental.id, full_name="Asha Rao",
                        phone="+919000000001", email="asha@example.com")
        sanjay = Customer(company_id=dental.id, full_name="Sanjay NoEmail",
                          phone="+919876543210", email=None)
        dev = Customer(company_id=shop.id, full_name="Dev Shop",
                       phone="+919000000001", email="dev@example.com")
        db.add_all([asha, sanjay, dev])
        db.flush()
        db.add(Invoice(
            company_id=dental.id, customer_id=asha.id, invoice_number="INV-1001",
            issued_at=datetime.now(timezone.utc), amount_minor=80000,
            status="unpaid", description="Cleaning",
        ))
        db.commit()
        return {
            "dental_id": dental.id, "shop_id": shop.id,
            "asha_id": asha.id, "dev_id": dev.id,
        }


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def headers(who: str, **extra) -> dict:
    return {"X-API-Key": KEYS[who], **extra}


@pytest.fixture
def h():
    return headers


class FakeN8n:
    """Replaces the real network call to n8n. mode: ok, 404 or down."""

    def __init__(self):
        self.mode = "ok"
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.mode == "down":
            raise httpx.ConnectError("n8n is down")
        code = 404 if self.mode == "404" else 200
        return httpx.Response(code, request=httpx.Request("POST", url))


@pytest.fixture
def n8n(monkeypatch):
    fake = FakeN8n()
    monkeypatch.setattr("app.events.httpx.post", fake.post)
    return fake


@pytest.fixture
def events():
    def _all():
        with SessionLocal() as db:
            rows = db.query(WorkflowEvent).order_by(WorkflowEvent.id).all()
            return [
                {"id": r.id, "company_id": r.company_id, "type": r.event_type,
                 "status": r.status, "attempts": r.attempts,
                 "error": r.last_error, "payload": r.payload}
                for r in rows
            ]
    return _all


def future_day(days_ahead: int = 3) -> str:
    """A bookable date: at least N days away, never a Sunday (the clinic is closed)."""
    d = date.today() + timedelta(days=days_ahead)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d.isoformat()


@pytest.fixture
def day():
    return future_day


def new_key() -> str:
    import uuid
    return uuid.uuid4().hex
