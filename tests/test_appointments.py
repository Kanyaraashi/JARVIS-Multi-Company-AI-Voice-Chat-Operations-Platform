"""Booking, double booking, cancel and reschedule."""
import threading
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import Appointment
from conftest import KEYS, new_key

ASHA = "+919000000001"
SANJAY = "+919876543210"


def book(client, h, day, time="10:00:00", phone=ASHA, who="dental", key=None):
    return client.post(
        "/appointments",
        json={"customer_phone": phone, "date": day, "time": time, "reason": "Checkup"},
        headers=h(who, **{"Idempotency-Key": key or new_key()}),
    )


def test_availability_lists_slots_and_hides_booked_ones(client, world, h, n8n, day):
    d = day()
    before = client.get("/appointments/availability", params={"date": d}, headers=h("dental")).json()
    assert before["open_slots"][0] == "09:00"
    assert before["open_slots"][-1] == "17:30"
    assert len(before["open_slots"]) == 18
    book(client, h, d, "09:30:00")
    after = client.get("/appointments/availability", params={"date": d}, headers=h("dental")).json()
    assert "09:30" not in after["open_slots"]
    assert len(after["open_slots"]) == 17


def test_sunday_has_no_slots_and_cannot_be_booked(client, world, h, n8n):
    d = date.today() + timedelta(days=3)
    while d.weekday() != 6:
        d += timedelta(days=1)
    assert client.get("/appointments/availability", params={"date": d.isoformat()},
                      headers=h("dental")).json()["open_slots"] == []
    assert book(client, h, d.isoformat()).status_code == 422


def test_booking_a_valid_slot(client, world, h, n8n, day, events):
    r = book(client, h, day(), "10:00:00")
    assert r.status_code == 200
    appt = r.json()["appointment"]
    assert appt["status"] == "booked" and appt["time"] == "10:00"
    ev = events()
    assert [e["type"] for e in ev] == ["appointment_created"]
    assert ev[0]["status"] == "sent"
    assert n8n.calls[0]["headers"]["X-Jarvis-Secret"] == "test-secret"
    assert n8n.calls[0]["json"]["customer"]["email"] == "asha@example.com"


@pytest.mark.parametrize("time", ["08:00:00", "18:00:00", "10:15:00", "23:30:00"])
def test_off_grid_or_closed_times_are_rejected(client, world, h, n8n, day, time):
    assert book(client, h, day(), time).status_code == 422


def test_past_time_is_rejected(client, world, h, n8n):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert book(client, h, yesterday).status_code == 422


def test_unknown_customer_is_404(client, world, h, n8n, day):
    assert book(client, h, day(), phone="+910000000000").status_code == 404


def test_double_booking_is_refused(client, world, h, n8n, day):
    d = day()
    assert book(client, h, d, "11:00:00").status_code == 200
    second = book(client, h, d, "11:00:00", phone=SANJAY)
    assert second.status_code == 409
    with SessionLocal() as db:
        assert db.query(Appointment).count() == 1


def test_double_booking_race_creates_only_one(client, world, h, n8n, day):
    """Two requests for the same slot at the same moment: exactly one wins."""
    d = day()
    results = []

    def attempt(phone):
        results.append(book(client, h, d, "12:00:00", phone=phone).status_code)

    threads = [threading.Thread(target=attempt, args=(p,)) for p in (ASHA, SANJAY)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409]
    with SessionLocal() as db:
        assert db.query(Appointment).filter_by(status="booked").count() == 1


def test_database_index_blocks_double_booking_even_without_the_api(client, world, h, n8n, day):
    d = day()
    appt = book(client, h, d, "13:00:00").json()["appointment"]
    with SessionLocal() as db:
        row = db.get(Appointment, appt["id"])
        with pytest.raises(IntegrityError):
            db.execute(text(
                "INSERT INTO appointments (company_id, customer_id, starts_at, ends_at,"
                " idempotency_key) VALUES (:c, :cust, :s, :e, 'raw-key-12345')"
            ), {"c": row.company_id, "cust": row.customer_id, "s": row.starts_at, "e": row.ends_at})
            db.commit()


def test_cancelled_slot_can_be_booked_again(client, world, h, n8n, day):
    d = day()
    appt = book(client, h, d, "14:00:00").json()["appointment"]["id"]
    assert client.post(f"/appointments/{appt}/cancel", json={"customer_phone": ASHA},
                       headers=h("dental")).json()["changed"] is True
    assert book(client, h, d, "14:00:00", phone=SANJAY).status_code == 200


def test_list_my_appointments(client, world, h, n8n, day):
    d = day()
    book(client, h, d, "10:00:00")
    book(client, h, d, "10:30:00")
    mine = client.get("/customers/appointments", params={"phone": ASHA}, headers=h("dental")).json()
    assert [a["time"] for a in mine] == ["10:00", "10:30"]
    assert client.get("/customers/appointments", params={"phone": SANJAY},
                      headers=h("dental")).json() == []
    assert client.get("/customers/appointments", params={"phone": "+910000000000"},
                      headers=h("dental")).status_code == 404


def test_get_appointment(client, world, h, n8n, day):
    appt = book(client, h, day()).json()["appointment"]["id"]
    assert client.get(f"/appointments/{appt}", headers=h("dental")).json()["id"] == appt
    assert client.get("/appointments/99999", headers=h("dental")).status_code == 404


def test_cancel_sends_one_email_and_repeat_changes_nothing(client, world, h, n8n, day, events):
    appt = book(client, h, day()).json()["appointment"]["id"]
    first = client.post(f"/appointments/{appt}/cancel", json={"customer_phone": ASHA}, headers=h("dental"))
    second = client.post(f"/appointments/{appt}/cancel", json={"customer_phone": ASHA}, headers=h("dental"))
    assert first.json()["changed"] is True and first.json()["appointment"]["status"] == "cancelled"
    assert second.json()["changed"] is False
    assert [e["type"] for e in events()].count("appointment_cancelled") == 1


def test_cancel_by_a_different_customer_is_refused(client, world, h, n8n, day):
    appt = book(client, h, day()).json()["appointment"]["id"]
    r = client.post(f"/appointments/{appt}/cancel", json={"customer_phone": SANJAY}, headers=h("dental"))
    assert r.status_code == 404
    assert client.get(f"/appointments/{appt}", headers=h("dental")).json()["status"] == "booked"


def test_cancel_needs_the_customer_phone(client, world, h):
    assert client.post("/appointments/1/cancel", json={}, headers=h("dental")).status_code == 422


def test_cancel_a_completed_appointment_is_refused(client, world, h, n8n, day):
    appt = book(client, h, day()).json()["appointment"]["id"]
    with SessionLocal() as db:
        db.execute(text("UPDATE appointments SET status='completed' WHERE id=:i"), {"i": appt})
        db.commit()
    r = client.post(f"/appointments/{appt}/cancel", json={"customer_phone": ASHA}, headers=h("dental"))
    assert r.status_code == 409
    r = client.post(f"/appointments/{appt}/reschedule",
                    json={"customer_phone": ASHA, "date": day(), "time": "16:00:00"}, headers=h("dental"))
    assert r.status_code == 409


def test_reschedule_moves_the_appointment_and_emails_once(client, world, h, n8n, day, events):
    d = day()
    appt = book(client, h, d, "10:00:00").json()["appointment"]["id"]
    body = {"customer_phone": ASHA, "date": d, "time": "15:00:00"}
    first = client.post(f"/appointments/{appt}/reschedule", json=body, headers=h("dental"))
    again = client.post(f"/appointments/{appt}/reschedule", json=body, headers=h("dental"))
    assert first.json()["changed"] is True and first.json()["appointment"]["time"] == "15:00"
    assert again.json()["changed"] is False
    resched = [e for e in events() if e["type"] == "appointment_rescheduled"]
    assert len(resched) == 1
    assert resched[0]["payload"]["appointment"]["old_time"] == "10:00 AM"
    assert resched[0]["payload"]["appointment"]["time"] == "03:00 PM"
    # the old slot is free again
    free = client.get("/appointments/availability", params={"date": d}, headers=h("dental")).json()
    assert "10:00" in free["open_slots"] and "15:00" not in free["open_slots"]


def test_reschedule_into_a_taken_slot_is_refused(client, world, h, n8n, day):
    d = day()
    book(client, h, d, "10:00:00", phone=SANJAY)
    mine = book(client, h, d, "11:00:00").json()["appointment"]["id"]
    r = client.post(f"/appointments/{mine}/reschedule",
                    json={"customer_phone": ASHA, "date": d, "time": "10:00:00"}, headers=h("dental"))
    assert r.status_code == 409
    assert client.get(f"/appointments/{mine}", headers=h("dental")).json()["time"] == "11:00"


def test_reschedule_validations(client, world, h, n8n, day):
    d = day()
    appt = book(client, h, d, "10:00:00").json()["appointment"]["id"]
    url = f"/appointments/{appt}/reschedule"
    bad_time = client.post(url, json={"customer_phone": ASHA, "date": d, "time": "03:00:00"}, headers=h("dental"))
    past = client.post(url, json={"customer_phone": ASHA,
                                  "date": (date.today() - timedelta(days=2)).isoformat(),
                                  "time": "10:00:00"}, headers=h("dental"))
    other = client.post(url, json={"customer_phone": SANJAY, "date": d, "time": "16:00:00"}, headers=h("dental"))
    no_time = client.post(url, json={"customer_phone": ASHA}, headers=h("dental"))
    assert (bad_time.status_code, past.status_code, other.status_code, no_time.status_code) == (422, 422, 404, 422)
