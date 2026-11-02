"""Per-company settings: staff email, opening hours, slot length, closed days."""
import pytest

from conftest import AdminSession as SessionLocal
from app.models import Company
from conftest import new_key

ASHA = "+919000000001"


def patch(client, h, body, who="dental_staff"):
    return client.patch("/staff/company", json=body, headers=h(who))


def slots(client, h, d, who="dental"):
    return client.get("/appointments/availability", params={"date": d}, headers=h(who)).json()["open_slots"]


def test_staff_can_read_settings(client, world, h):
    body = client.get("/staff/company", headers=h("dental_staff")).json()
    assert body == {"slug": "smile-dental", "name": "Smile Dental", "timezone": "Asia/Kolkata",
                    "staff_email": None, "open_hour": 9, "close_hour": 18,
                    "slot_minutes": 30, "closed_weekdays": [6]}


def test_ai_key_cannot_read_or_change_settings(client, world, h):
    assert client.get("/staff/company", headers=h("dental")).status_code == 401
    assert patch(client, h, {"open_hour": 8}, who="dental").status_code == 401


def test_change_only_what_is_sent(client, world, h):
    r = patch(client, h, {"staff_email": "frontdesk@smile.example"})
    assert r.status_code == 200
    body = r.json()
    assert body["staff_email"] == "frontdesk@smile.example"
    assert (body["open_hour"], body["close_hour"], body["slot_minutes"]) == (9, 18, 30)


def test_staff_email_can_be_removed(client, world, h):
    patch(client, h, {"staff_email": "frontdesk@smile.example"})
    assert patch(client, h, {"staff_email": None}).json()["staff_email"] is None


def test_one_company_changing_settings_does_not_affect_the_other(client, world, h):
    patch(client, h, {"staff_email": "a@dental.example", "open_hour": 10, "slot_minutes": 60})
    shop = client.get("/staff/company", headers=h("shop_staff")).json()
    assert shop["staff_email"] is None and shop["open_hour"] == 9 and shop["slot_minutes"] == 30


@pytest.mark.parametrize("body", [
    {"open_hour": 18, "close_hour": 9},          # opens after it closes
    {"open_hour": 12, "close_hour": 12},
    {"open_hour": -1},
    {"close_hour": 25},
    {"close_hour": 8},                            # before the current open hour (9)
    {"slot_minutes": 25},
    {"closed_weekdays": [7]},
    {"closed_weekdays": ["sunday"]},
    {"staff_email": "not-an-email"},
    {"timezone": "Mars/Phobos"},
])
def test_invalid_settings_are_rejected_and_nothing_changes(client, world, h, body):
    assert patch(client, h, body).status_code == 422
    after = client.get("/staff/company", headers=h("dental_staff")).json()
    assert (after["open_hour"], after["close_hour"], after["slot_minutes"]) == (9, 18, 30)


def test_closed_days_are_sorted_and_deduplicated(client, world, h):
    assert patch(client, h, {"closed_weekdays": [6, 5, 6]}).json()["closed_weekdays"] == [5, 6]


def test_database_itself_rejects_impossible_hours(world):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    with SessionLocal() as db:
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE companies SET open_hour=20, close_hour=10 WHERE id=:i"),
                       {"i": world["dental_id"]})
            db.commit()


def test_new_hours_change_availability(client, world, h, day):
    d = day()
    patch(client, h, {"open_hour": 10, "close_hour": 12})
    assert slots(client, h, d) == ["10:00", "10:30", "11:00", "11:30"]
    assert len(slots(client, h, d, who="shop")) == 18  # the other company is untouched


def test_new_slot_length_changes_availability_and_appointment_length(client, world, h, n8n, day):
    d = day()
    patch(client, h, {"slot_minutes": 60})
    assert slots(client, h, d)[:3] == ["09:00", "10:00", "11:00"]
    r = client.post("/appointments", json={"customer_phone": ASHA, "date": d, "time": "10:00:00"},
                    headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert r.status_code == 200
    # a 30-minute time is no longer a valid start
    r = client.post("/appointments", json={"customer_phone": ASHA, "date": d, "time": "11:30:00"},
                    headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert r.status_code == 422


def test_last_slot_must_finish_before_closing(client, world, h, day):
    patch(client, h, {"open_hour": 9, "close_hour": 17, "slot_minutes": 45})
    d = day()
    free = slots(client, h, d)
    assert free[-1] == "15:45"        # 15:45 + 45 min = 16:30
    assert "16:30" not in free        # 16:30 + 45 min = 17:15, after closing


def test_closing_another_weekday(client, world, h, day):
    from datetime import date, timedelta
    d = date.today() + timedelta(days=3)
    while d.weekday() != 2:                       # find a Wednesday
        d += timedelta(days=1)
    assert slots(client, h, d.isoformat()) != []
    patch(client, h, {"closed_weekdays": [2, 6]})
    assert slots(client, h, d.isoformat()) == []


def test_open_sunday_when_configured(client, world, h):
    from datetime import date, timedelta
    d = date.today() + timedelta(days=3)
    while d.weekday() != 6:
        d += timedelta(days=1)
    assert slots(client, h, d.isoformat()) == []
    patch(client, h, {"closed_weekdays": []})
    assert slots(client, h, d.isoformat()) != []


def test_existing_bookings_that_overlap_a_longer_slot_block_it(client, world, h, n8n, day):
    d = day()
    client.post("/appointments", json={"customer_phone": ASHA, "date": d, "time": "10:30:00"},
                headers=h("dental", **{"Idempotency-Key": new_key()}))
    patch(client, h, {"slot_minutes": 60})
    free = slots(client, h, d)
    assert "10:00" not in free             # 10:00-11:00 overlaps the 10:30 booking
    assert "09:00" in free and "11:00" in free  # these only touch it
    r = client.post("/appointments", json={"customer_phone": "+919876543210", "date": d, "time": "10:00:00"},
                    headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert r.status_code == 409


def test_staff_email_travels_with_alert_events(client, world, h, n8n, events):
    patch(client, h, {"staff_email": "frontdesk@smile.example"})
    client.post("/tickets", json={"subject": "Help me", "description": "Please help"},
                headers=h("dental", **{"Idempotency-Key": new_key()}))
    client.post("/escalations", json={"reason": "Call me back"},
                headers=h("dental", **{"Idempotency-Key": new_key()}))
    sent = [c["json"] for c in n8n.calls]
    assert [s["event_type"] for s in sent] == ["ticket_created", "escalation_created"]
    assert all(s["company"]["staff_email"] == "frontdesk@smile.example" for s in sent)


def test_events_of_a_company_without_staff_email_carry_null(client, world, h, n8n):
    client.post("/tickets", json={"subject": "Help me", "description": "Please help"},
                headers=h("shop", **{"Idempotency-Key": new_key()}))
    assert n8n.calls[0]["json"]["company"]["staff_email"] is None


def test_escalation_business_hours_use_company_settings(client, world, h, n8n, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app import escalations

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 1, 7, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # Monday 20:00

    monkeypatch.setattr(escalations, "datetime", Fixed)
    body = {"reason": "Call me back"}
    r = client.post("/escalations", json=body, headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert r.json()["within_business_hours"] is False
    patch(client, h, {"close_hour": 22})
    r = client.post("/escalations", json=body, headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert r.json()["within_business_hours"] is True
