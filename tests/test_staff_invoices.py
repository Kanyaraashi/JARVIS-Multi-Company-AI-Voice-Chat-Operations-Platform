"""Staff keys, ticket updates, and invoice emails."""
from datetime import datetime, timedelta, timezone

from conftest import AdminSession as SessionLocal
from app.models import Customer, Invoice, TicketUpdate, WorkflowEvent
from conftest import new_key

ASHA = "+919000000001"
SANJAY = "+919876543210"


def ticket(client, h, who="dental", phone=ASHA):
    return client.post("/tickets", json={"subject": "Crown fell off", "description": "Please call",
                                         "customer_phone": phone},
                       headers=h(who, **{"Idempotency-Key": new_key()})).json()["ticket"]["id"]


# ---------- key types are not interchangeable ----------

def test_ai_key_cannot_use_staff_endpoints(client, world, h):
    assert client.get("/staff/tickets", headers=h("dental")).status_code == 401
    assert client.patch("/staff/tickets/1", json={"status": "resolved"}, headers=h("dental")).status_code == 401


def test_staff_key_cannot_use_ai_endpoints(client, world, h):
    assert client.get("/company/me", headers=h("dental_staff")).status_code == 401
    assert client.post("/tickets", json={"subject": "Hello", "description": "Hi there"},
                       headers=h("dental_staff", **{"Idempotency-Key": new_key()})).status_code == 401


def test_inactive_company_is_blocked(client, world, h):
    from sqlalchemy import text
    with SessionLocal() as db:
        db.execute(text("UPDATE companies SET is_active=false WHERE id=:i"), {"i": world["dental_id"]})
        db.commit()
    assert client.get("/company/me", headers=h("dental")).status_code == 403


def test_revoked_key_stops_working(client, world, h):
    from sqlalchemy import text
    with SessionLocal() as db:
        db.execute(text("UPDATE api_keys SET is_active=false"))
        db.commit()
    assert client.get("/company/me", headers=h("dental")).status_code == 401


# ---------- staff ticket list ----------

def test_staff_sees_only_own_company_tickets(client, world, h, n8n):
    mine = ticket(client, h)
    ticket(client, h, "shop", phone=ASHA)
    listed = client.get("/staff/tickets", headers=h("dental_staff")).json()
    assert [t["id"] for t in listed] == [mine]
    assert listed[0]["customer_name"] == "Asha Rao"
    assert client.get("/staff/tickets", params={"status": "resolved"},
                      headers=h("dental_staff")).json() == []
    assert client.get("/staff/tickets", params={"status": "nonsense"},
                      headers=h("dental_staff")).status_code == 422


def test_staff_cannot_touch_another_companys_ticket(client, world, h, n8n):
    other = ticket(client, h, "shop")
    r = client.patch(f"/staff/tickets/{other}", json={"status": "resolved"}, headers=h("dental_staff"))
    assert r.status_code == 404


# ---------- staff ticket update ----------

def test_update_saves_history_and_queues_exactly_one_email(client, world, h, n8n, events):
    t = ticket(client, h)
    r = client.patch(f"/staff/tickets/{t}", json={"status": "in_progress", "note": "  Looking now "},
                     headers=h("dental_staff"))
    assert r.json()["changed"] is True and r.json()["ticket"]["status"] == "in_progress"
    with SessionLocal() as db:
        rows = db.query(TicketUpdate).all()
        assert len(rows) == 1
        assert (rows[0].old_status, rows[0].new_status, rows[0].note) == ("open", "in_progress", "Looking now")
    updated = [e for e in events() if e["type"] == "ticket_updated"]
    assert len(updated) == 1
    assert updated[0]["payload"]["customer"]["email"] == "asha@example.com"
    assert updated[0]["payload"]["note"] == "Looking now"


def test_same_status_twice_sends_no_second_email(client, world, h, n8n, events):
    t = ticket(client, h)
    client.patch(f"/staff/tickets/{t}", json={"status": "resolved"}, headers=h("dental_staff"))
    again = client.patch(f"/staff/tickets/{t}", json={"status": "resolved"}, headers=h("dental_staff"))
    assert again.json()["changed"] is False
    assert [e["type"] for e in events()].count("ticket_updated") == 1
    with SessionLocal() as db:
        assert db.query(TicketUpdate).count() == 1


def test_closed_ticket_cannot_be_reopened(client, world, h, n8n):
    t = ticket(client, h)
    client.patch(f"/staff/tickets/{t}", json={"status": "closed"}, headers=h("dental_staff"))
    r = client.patch(f"/staff/tickets/{t}", json={"status": "in_progress"}, headers=h("dental_staff"))
    assert r.status_code == 409


def test_invalid_status_is_rejected(client, world, h, n8n):
    t = ticket(client, h)
    assert client.patch(f"/staff/tickets/{t}", json={"status": "open"}, headers=h("dental_staff")).status_code == 422
    assert client.patch(f"/staff/tickets/{t}", json={"status": "banana"}, headers=h("dental_staff")).status_code == 422


def test_ticket_without_customer_can_be_updated(client, world, h, n8n, events):
    t = client.post("/escalations", json={"reason": "Unknown caller"},
                    headers=h("dental", **{"Idempotency-Key": new_key()})).json()["ticket"]["id"]
    r = client.patch(f"/staff/tickets/{t}", json={"status": "resolved"}, headers=h("dental_staff"))
    assert r.status_code == 200 and r.json()["ticket"]["customer_name"] is None


def test_customer_sees_the_new_status(client, world, h, n8n):
    t = ticket(client, h)
    client.patch(f"/staff/tickets/{t}", json={"status": "resolved"}, headers=h("dental_staff"))
    seen = client.get(f"/tickets/{t}", params={"customer_phone": ASHA}, headers=h("dental"))
    assert seen.json()["status"] == "resolved"


# ---------- invoices ----------

def request_invoice(client, h, who="dental", phone=ASHA):
    return client.post("/invoices/email-request", json={"customer_phone": phone}, headers=h(who))


def test_invoice_response_has_no_money_details(client, world, h, n8n, events):
    r = request_invoice(client, h)
    assert r.status_code == 200
    body = r.json()
    assert body == {"requested": True, "already_requested": False, "email_hint": "a***@example.com"}
    assert "800" not in r.text and "INV-" not in r.text
    ev = events()[0]
    assert ev["type"] == "invoice_requested" and ev["status"] == "sent"
    assert ev["payload"]["invoice"]["amount"] == "INR 800.00"
    assert ev["payload"]["invoice"]["status"] == "UNPAID"


def test_invoice_cooldown_prevents_a_second_email(client, world, h, n8n, events):
    request_invoice(client, h)
    again = request_invoice(client, h)
    assert again.json()["already_requested"] is True
    assert len(events()) == 1 and len(n8n.calls) == 1


def test_invoice_can_be_requested_again_after_the_cooldown(client, world, h, n8n, events):
    from sqlalchemy import text
    request_invoice(client, h)
    with SessionLocal() as db:
        db.execute(text("UPDATE workflow_events SET created_at = now() - interval '30 minutes'"))
        db.commit()
    assert request_invoice(client, h).json()["already_requested"] is False
    assert len(events()) == 2


def test_latest_invoice_is_the_one_sent(client, world, h, n8n, events):
    with SessionLocal() as db:
        db.add(Invoice(company_id=world["dental_id"], customer_id=world["asha_id"],
                       invoice_number="INV-2000", issued_at=datetime.now(timezone.utc) + timedelta(days=1),
                       amount_minor=123456, status="paid", description="Filling"))
        db.commit()
    request_invoice(client, h)
    assert events()[0]["payload"]["invoice"]["number"] == "INV-2000"
    assert events()[0]["payload"]["invoice"]["amount"] == "INR 1,234.56"


def test_invoice_for_customer_without_email_is_refused(client, world, h, n8n):
    r = request_invoice(client, h, phone=SANJAY)
    assert r.status_code == 422 and "no email" in r.json()["detail"].lower()


def test_invoice_for_customer_without_invoices_is_404(client, world, h, n8n):
    with SessionLocal() as db:
        db.add(Customer(company_id=world["dental_id"], full_name="No Bills", phone="+919111111111",
                        email="nobills@example.com"))
        db.commit()
    assert request_invoice(client, h, phone="+919111111111").status_code == 404


def test_invoice_unknown_customer_is_404(client, world, h, n8n):
    assert request_invoice(client, h, phone="+910000000000").status_code == 404
