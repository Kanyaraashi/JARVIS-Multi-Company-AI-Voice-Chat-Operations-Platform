"""Step 28: what the dashboard's Tickets section needs from the API."""
from conftest import AdminSession, KEYS
from app.models import AuditLog, Customer, WorkflowEvent
from conftest import new_key

ASHA = "+919000000001"


def make(client, h, who="dental", phone=ASHA, subject="Crown fell off"):
    return client.post("/tickets", json={"subject": subject, "description": "Please call", "customer_phone": phone},
                       headers=h(who, **{"Idempotency-Key": new_key()})).json()["ticket"]["id"]


def listing(client, h, who="dental_staff", **params):
    return client.get("/staff/tickets", params=params, headers=h(who)).json()


def test_a_new_ticket_shows_the_customer_email_and_no_status_email_yet(client, world, h, n8n):
    make(client, h)
    row = listing(client, h)[0]
    assert row["customer_email"] == "asha@example.com" and row["update_email"] is None


def test_status_email_is_reported_as_sent_when_n8n_accepted_it(client, world, h, n8n):
    t = make(client, h)
    r = client.patch(f"/staff/tickets/{t}", json={"status": "resolved", "note": "Fixed"}, headers=h("dental_staff"))
    assert r.json()["ticket"]["update_email"] == "pending"          # queued at the moment of the change
    assert listing(client, h)[0]["update_email"] == "sent"          # the background send has finished
    again = client.patch(f"/staff/tickets/{t}", json={"status": "resolved"}, headers=h("dental_staff"))
    assert again.json()["changed"] is False and again.json()["ticket"]["update_email"] == "sent"


def test_a_failed_email_is_visible_and_can_be_resent_once_n8n_is_back(client, world, h, n8n, events):
    t = make(client, h)
    n8n.mode = "down"
    client.patch(f"/staff/tickets/{t}", json={"status": "in_progress"}, headers=h("dental_staff"))
    assert listing(client, h)[0]["update_email"] == "failed"
    n8n.mode = "ok"
    r = client.post(f"/staff/tickets/{t}/resend-email", headers=h("dental_staff"))
    assert r.status_code == 200 and r.json()["queued"] is True
    assert listing(client, h)[0]["update_email"] == "sent"
    assert [e["type"] for e in events()].count("ticket_updated") == 1       # the same email, not a second one
    with AdminSession() as db:
        assert db.query(AuditLog).filter(AuditLog.action == "ticket.resend_email").count() == 1
    again = client.post(f"/staff/tickets/{t}/resend-email", headers=h("dental_staff"))
    assert again.status_code == 409                                         # never send twice by accident


def test_resend_is_refused_when_nothing_was_queued_and_for_other_companies(client, world, h, n8n):
    t = make(client, h)
    assert client.post(f"/staff/tickets/{t}/resend-email", headers=h("dental_staff")).status_code == 404
    n8n.mode = "down"
    client.patch(f"/staff/tickets/{t}", json={"status": "resolved"}, headers=h("dental_staff"))
    assert client.post(f"/staff/tickets/{t}/resend-email", headers=h("shop_staff")).status_code == 404   # other company
    assert client.post(f"/staff/tickets/{t}/resend-email", headers=h("dental")).status_code == 401       # AI key
    assert client.post(f"/staff/tickets/{t}/resend-email").status_code == 401
    assert listing(client, h, "shop_staff") == []                                                         # never listed


def test_a_customer_without_email_is_shown_so_staff_can_warn_instead_of_waiting(client, world, h, n8n):
    t = make(client, h)
    with AdminSession() as db:
        db.query(Customer).filter(Customer.phone == ASHA).update({"email": None})
        db.commit()
    assert listing(client, h)[0]["customer_email"] is None
