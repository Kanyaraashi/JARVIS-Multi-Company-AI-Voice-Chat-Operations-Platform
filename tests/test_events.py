"""n8n down means the work is still saved, and recovery sends it later."""
from app.db import SessionLocal
from app.models import SupportTicket, WorkflowEvent
from conftest import KEYS, new_key


def create_ticket(client, h):
    return client.post("/tickets", json={"subject": "Printer", "description": "Does not print",
                                         "customer_phone": "+919000000001"},
                       headers=h("dental", **{"Idempotency-Key": new_key()}))


def test_ticket_event_is_sent(client, world, h, n8n, events):
    assert create_ticket(client, h).status_code == 200
    ev = events()
    assert len(ev) == 1 and ev[0]["status"] == "sent" and ev[0]["attempts"] == 1
    assert n8n.calls[0]["json"]["event_type"] == "ticket_created"


def test_n8n_down_still_saves_the_ticket_and_the_customer_gets_success(client, world, h, n8n, events):
    n8n.mode = "down"
    r = create_ticket(client, h)
    assert r.status_code == 200  # the customer is not told "failed"
    with SessionLocal() as db:
        assert db.query(SupportTicket).count() == 1
    ev = events()
    assert ev[0]["status"] == "failed" and "n8n is down" in ev[0]["error"]


def test_n8n_returning_404_is_recorded_as_failed(client, world, h, n8n, events):
    n8n.mode = "404"
    create_ticket(client, h)
    assert events()[0]["status"] == "failed"
    assert "404" in events()[0]["error"]


def test_retry_delivers_the_failed_event_once_n8n_is_back(client, world, h, n8n, events, monkeypatch):
    n8n.mode = "down"
    create_ticket(client, h)
    monkeypatch.setattr("app.internal.MIN_AGE_MINUTES", 0)
    n8n.mode = "ok"
    r = client.post("/internal/retry-events", headers={"X-Jarvis-Secret": "test-secret"})
    assert r.status_code == 200
    assert r.json() == {"retried": 1, "gave_up": 0, "still_failing": 0}
    assert events()[0]["status"] == "sent" and events()[0]["attempts"] == 2
    # and a second retry run does nothing, so no duplicate emails
    r = client.post("/internal/retry-events", headers={"X-Jarvis-Secret": "test-secret"})
    assert r.json()["retried"] == 0
    assert len(n8n.calls) == 2


def test_retry_skips_very_fresh_events(client, world, h, n8n, events):
    n8n.mode = "down"
    create_ticket(client, h)
    n8n.mode = "ok"
    r = client.post("/internal/retry-events", headers={"X-Jarvis-Secret": "test-secret"})
    assert r.json()["retried"] == 0  # the API's own first attempt may still be running


def test_retry_gives_up_after_max_attempts_and_reports_it(client, world, h, n8n, events, monkeypatch):
    n8n.mode = "down"
    create_ticket(client, h)
    monkeypatch.setattr("app.internal.MIN_AGE_MINUTES", 0)
    for _ in range(10):
        client.post("/internal/retry-events", headers={"X-Jarvis-Secret": "test-secret"})
    assert events()[0]["attempts"] == 5
    r = client.post("/internal/retry-events", headers={"X-Jarvis-Secret": "test-secret"})
    assert r.json() == {"retried": 0, "gave_up": 1, "still_failing": 1}


def test_retry_endpoint_needs_the_secret(client, world):
    assert client.post("/internal/retry-events").status_code == 401
    assert client.post("/internal/retry-events", headers={"X-Jarvis-Secret": "wrong"}).status_code == 401
    assert client.post("/internal/retry-events", headers={"X-Jarvis-Secret": KEYS["dental"]}).status_code == 401


def test_missing_webhook_configuration_is_recorded(client, world, h, n8n, events, monkeypatch):
    monkeypatch.setitem(__import__("app.events", fromlist=["x"]).WEBHOOK_URLS, "ticket_created", None)
    create_ticket(client, h)
    assert events()[0]["status"] == "failed"
    assert "not configured" in events()[0]["error"]


def test_sent_event_is_never_sent_twice(world, n8n):
    from app.events import send_event
    with SessionLocal() as db:
        ev = WorkflowEvent(company_id=world["dental_id"], event_type="ticket_created", payload={"a": 1})
        db.add(ev)
        db.commit()
        event_id = ev.id
    send_event(event_id)
    send_event(event_id)
    send_event(99999)  # unknown id is ignored
    assert len(n8n.calls) == 1


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
