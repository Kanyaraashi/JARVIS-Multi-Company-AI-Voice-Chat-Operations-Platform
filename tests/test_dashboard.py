"""Step 26: the staff dashboard numbers. Each company sees only its own."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.dashboard import day_bounds
from app.models import Appointment, CallRecord, Customer, Invoice, SupportTicket, WorkflowEvent
from conftest import AdminSession, KEYS

NOW = datetime.now(timezone.utc)


def staff(who="dental_staff"):
    return {"X-API-Key": KEYS[who]}


def get(client, who="dental_staff", **params):
    r = client.get("/staff/dashboard", params=params, headers=staff(who))
    assert r.status_code == 200, r.text
    return r.json()


def add_call(db, company_id, outcome="completed", hours_ago=1, turns=None, room=None):
    started = NOW - timedelta(hours=hours_ago)
    db.add(CallRecord(
        company_id=company_id, room_name=room or f"call-{company_id}-{outcome}-{hours_ago}-{id(turns)}",
        direction="inbound", started_at=started, ended_at=started + timedelta(seconds=60),
        duration_seconds=60, outcome=outcome, turn_count=1, transcript=[], tools_used=[],
        latency_turns=turns or [], providers={},
    ))


def test_an_empty_company_shows_zeros_and_no_made_up_percentages(client, world):
    with AdminSession() as db:           # remove the seeded invoice so the company is really empty
        db.query(Invoice).delete()
        db.commit()
    data = get(client)
    assert data["company"]["slug"] == "smile-dental"
    assert data["tickets"] == {"open": 0, "in_progress": 0, "urgent_open": 0, "created_today": 0}
    assert data["appointments"]["upcoming"] == [] and data["invoices"]["unpaid_count"] == 0
    assert data["calls"]["total"] == 0 and data["calls"]["answered_without_trouble_pct"] is None
    assert data["calls"]["speed"]["avg_ms"] is None and data["attention"] == []


def test_counts_are_only_for_the_callers_own_company(client, world):
    with AdminSession() as db:
        for company_id, customer_id in ((world["dental_id"], world["asha_id"]), (world["shop_id"], world["dev_id"])):
            db.add(SupportTicket(company_id=company_id, customer_id=customer_id, subject="s", description="d"))
        db.add(SupportTicket(company_id=world["dental_id"], customer_id=world["asha_id"], subject="s2",
                             description="d", status="in_progress", priority="urgent"))
        add_call(db, world["dental_id"], "completed")
        add_call(db, world["shop_id"], "failed")
        add_call(db, world["shop_id"], "failed", hours_ago=2)
        db.commit()
    dental, shop = get(client), get(client, "shop_staff")
    assert (dental["tickets"]["open"], dental["tickets"]["in_progress"], dental["tickets"]["urgent_open"]) == (1, 1, 1)
    assert (shop["tickets"]["open"], shop["tickets"]["in_progress"]) == (1, 0)
    assert dental["calls"]["total"] == 1 and shop["calls"]["total"] == 2
    assert dental["calls"]["by_outcome"]["failed"] == 0 and shop["calls"]["by_outcome"]["failed"] == 2
    assert [a["kind"] for a in dental["attention"]] == ["urgent_tickets"]
    assert [a["kind"] for a in shop["attention"]] == ["failed_calls"]


def test_appointments_show_only_booked_future_ones_with_the_customer_name(client, world):
    with AdminSession() as db:
        def appt(offset_hours, status="booked", customer=world["asha_id"], key="k"):
            start = NOW + timedelta(hours=offset_hours)
            db.add(Appointment(company_id=world["dental_id"], customer_id=customer, starts_at=start,
                               ends_at=start + timedelta(minutes=30), reason="Checkup", status=status,
                               idempotency_key=f"{key}-{offset_hours}-{status}"))
        appt(30)
        appt(50)
        appt(24 * 20)                          # too far away for next 7 days
        appt(40, status="cancelled")
        appt(-5)                               # already past
        db.commit()
    data = get(client)["appointments"]
    assert data["next_7_days"] == 2
    assert [u["customer_name"] for u in data["upcoming"]] == ["Asha Rao"] * 3
    assert all(u["reason"] == "Checkup" for u in data["upcoming"])
    assert [u["starts_at"] for u in data["upcoming"]] == sorted(u["starts_at"] for u in data["upcoming"])
    assert get(client, "shop_staff")["appointments"]["upcoming"] == []


def test_unpaid_invoices_are_never_added_across_currencies(client, world):
    with AdminSession() as db:
        for number, amount, currency, status in (("INV-2", 5000, "INR", "unpaid"), ("INV-3", 700, "USD", "unpaid"),
                                                 ("INV-4", 9999, "INR", "paid")):
            db.add(Invoice(company_id=world["dental_id"], customer_id=world["asha_id"], invoice_number=number,
                           issued_at=NOW, amount_minor=amount, currency=currency, status=status, description="x"))
        db.commit()
    inv = get(client)["invoices"]
    assert inv["unpaid_count"] == 3                                    # seeded INV-1001 (80000 INR) plus two
    assert inv["unpaid_by_currency"] == [
        {"currency": "INR", "count": 2, "total_minor": 85000},
        {"currency": "USD", "count": 1, "total_minor": 700},
    ]


def test_the_call_summary_and_honest_speed_numbers(client, world):
    fast = [{"total_ms": 900, "llm_real_ms": 800}]
    slow = [{"total_ms": 2600, "llm_real_ms": 9000, "filler": True, "switched": True}]
    with AdminSession() as db:
        add_call(db, world["dental_id"], "completed", 1, fast)
        add_call(db, world["dental_id"], "handoff", 2, slow)
        add_call(db, world["dental_id"], "failed", 3)
        add_call(db, world["dental_id"], "abandoned", 4)
        add_call(db, world["dental_id"], "completed", hours_ago=24 * 10)   # older than 7 days
        db.commit()
    calls = get(client)["calls"]
    assert calls["total"] == 4 and calls["by_outcome"] == {"completed": 1, "handoff": 1, "abandoned": 1, "failed": 1}
    assert calls["answered_without_trouble_pct"] == 50
    assert calls["speed"]["turns"] == 2 and calls["speed"]["avg_ms"] == 1750
    assert calls["speed"]["avg_llm_real_ms"] == 4900
    assert calls["speed"]["filler_pct"] == 50 and calls["speed"]["switched_pct"] == 50
    assert get(client, days=30)["calls"]["total"] == 5


def test_failed_notifications_are_flagged(client, world):
    with AdminSession() as db:
        db.add(WorkflowEvent(company_id=world["dental_id"], event_type="ticket_created", payload={}, status="failed"))
        db.add(WorkflowEvent(company_id=world["shop_id"], event_type="ticket_created", payload={}, status="sent"))
        db.commit()
    assert [a["kind"] for a in get(client)["attention"]] == ["failed_notifications"]
    assert get(client, "shop_staff")["attention"] == []


def test_today_follows_the_companys_own_time_zone():
    zone = ZoneInfo("Asia/Kolkata")
    moment = datetime(2026, 11, 7, 20, 30, tzinfo=timezone.utc)    # 02:00 on 8 November in India
    start, end = day_bounds(moment, zone)
    assert start == datetime(2026, 11, 7, 18, 30, tzinfo=timezone.utc)
    assert end - start == timedelta(hours=24)
    assert ZoneInfo("UTC") and day_bounds(moment, ZoneInfo("UTC"))[0] == datetime(2026, 11, 7, tzinfo=timezone.utc)


def test_only_a_staff_key_opens_the_dashboard_and_bad_input_is_refused(client, world):
    assert client.get("/staff/dashboard").status_code == 401
    assert client.get("/staff/dashboard", headers={"X-API-Key": KEYS["dental"]}).status_code == 401   # AI key
    assert client.get("/staff/dashboard", params={"days": 0}, headers=staff()).status_code == 422
    assert client.get("/staff/dashboard", params={"days": 500}, headers=staff()).status_code == 422
