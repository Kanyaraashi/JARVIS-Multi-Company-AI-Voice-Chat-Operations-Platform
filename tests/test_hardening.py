"""Security hardening: rate limits, audit trail, ticket privacy, log redaction."""
import logging

import pytest

from app import ratelimit
from conftest import AdminSession as SessionLocal
from app.models import AuditLog
from app.privacy import redact
from conftest import new_key

ASHA = "+919000000001"
SANJAY = "+919876543210"


def audit_rows(action=None):
    with SessionLocal() as db:
        query = db.query(AuditLog).order_by(AuditLog.id)
        if action:
            query = query.filter_by(action=action)
        return [
            {"action": r.action, "actor_type": r.actor_type, "actor_label": r.actor_label,
             "target_type": r.target_type, "target_id": r.target_id, "details": r.details,
             "company_id": r.company_id, "ip": r.ip}
            for r in query.all()
        ]


# ---------- ticket status is private ----------

def make_ticket(client, h, phone):
    return client.post("/tickets", json={"subject": "Question", "description": "Please help me",
                                         "customer_phone": phone},
                       headers=h("dental", **{"Idempotency-Key": new_key()})).json()["ticket"]["id"]


def test_ticket_status_needs_the_matching_phone(client, world, h, n8n):
    t = make_ticket(client, h, ASHA)
    assert client.get(f"/tickets/{t}", params={"customer_phone": ASHA}, headers=h("dental")).json()["status"] == "open"
    assert client.get(f"/tickets/{t}", params={"customer_phone": "+91 90000 00001"}, headers=h("dental")).status_code == 200
    wrong = client.get(f"/tickets/{t}", params={"customer_phone": SANJAY}, headers=h("dental"))
    missing = client.get("/tickets/9999", params={"customer_phone": ASHA}, headers=h("dental"))
    assert wrong.status_code == missing.status_code == 404
    assert wrong.json() == missing.json()  # cannot tell "wrong phone" from "no such ticket"


def test_ticket_status_without_a_phone_is_refused(client, world, h, n8n):
    t = make_ticket(client, h, ASHA)
    assert client.get(f"/tickets/{t}", headers=h("dental")).status_code == 422


def test_ticket_without_a_customer_cannot_be_read_by_the_ai(client, world, h, n8n):
    t = client.post("/tickets", json={"subject": "Anonymous", "description": "No customer here"},
                    headers=h("dental", **{"Idempotency-Key": new_key()})).json()["ticket"]["id"]
    assert client.get(f"/tickets/{t}", params={"customer_phone": ASHA}, headers=h("dental")).status_code == 404


# ---------- customer lookup never gives out the email ----------

def test_customer_lookup_hides_the_email(client, world, h):
    r = client.get("/customers/lookup", params={"phone": ASHA}, headers=h("dental"))
    assert r.json() == {"id": world["asha_id"], "full_name": "Asha Rao", "phone": ASHA,
                        "has_email": True, "email_hint": "a***@example.com"}
    assert "asha@example.com" not in r.text
    r = client.get("/customers/lookup", params={"phone": SANJAY}, headers=h("dental"))
    assert r.json()["has_email"] is False and r.json()["email_hint"] is None


# ---------- rate limits ----------

def test_a_key_that_sends_too_many_requests_gets_429(client, world, h, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "3")
    for _ in range(3):
        assert client.get("/company/me", headers=h("dental")).status_code == 200
    blocked = client.get("/company/me", headers=h("dental"))
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert "Too many requests" in blocked.json()["detail"]


def test_one_companys_limit_does_not_block_the_other(client, world, h, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    for _ in range(3):
        client.get("/company/me", headers=h("dental"))
    assert client.get("/company/me", headers=h("dental")).status_code == 429
    assert client.get("/company/me", headers=h("shop")).status_code == 200


def test_limit_resets_after_the_window(client, world, h, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    now = [1000.0]
    monkeypatch.setattr(ratelimit.request_limiter, "clock", lambda: now[0])
    client.get("/company/me", headers=h("dental"))
    client.get("/company/me", headers=h("dental"))
    assert client.get("/company/me", headers=h("dental")).status_code == 429
    now[0] += 61
    assert client.get("/company/me", headers=h("dental")).status_code == 200


def test_guessing_keys_gets_the_address_blocked(client, world, h, monkeypatch):
    monkeypatch.setenv("AUTH_FAIL_PER_MINUTE", "3")
    for _ in range(3):
        assert client.get("/company/me", headers={"X-API-Key": "jrv_wrong_guess"}).status_code == 401
    assert client.get("/company/me", headers={"X-API-Key": "jrv_wrong_guess"}).status_code == 429
    # while blocked, even the right key is refused
    assert client.get("/company/me", headers=h("dental")).status_code == 429


def test_failed_attempts_expire(client, world, h, monkeypatch):
    monkeypatch.setenv("AUTH_FAIL_PER_MINUTE", "2")
    now = [500.0]
    monkeypatch.setattr(ratelimit.failure_limiter, "clock", lambda: now[0])
    for _ in range(2):
        client.get("/company/me")
    assert client.get("/company/me", headers=h("dental")).status_code == 429
    now[0] += 61
    assert client.get("/company/me", headers=h("dental")).status_code == 200


def test_wrong_internal_secret_is_also_counted(client, world, monkeypatch):
    monkeypatch.setenv("AUTH_FAIL_PER_MINUTE", "2")
    for _ in range(2):
        assert client.post("/internal/retry-events", headers={"X-Jarvis-Secret": "nope"}).status_code == 401
    assert client.post("/internal/retry-events", headers={"X-Jarvis-Secret": "test-secret"}).status_code == 429


def test_the_limiter_forgets_idle_keys():
    limiter = ratelimit.RateLimiter("NOT_SET_ANYWHERE", 5)
    now = [0.0]
    limiter.clock = lambda: now[0]
    for i in range(10005):
        limiter.hit(f"k{i}")
    now[0] += 120
    limiter.hit("fresh")
    assert len(limiter._hits) < 10


def test_bad_limit_setting_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "banana")
    assert ratelimit.request_limiter.limit == 120


# ---------- audit trail ----------

def test_changes_leave_an_audit_record(client, world, h, n8n, day):
    d = day()
    t = make_ticket(client, h, ASHA)
    appt = client.post("/appointments", json={"customer_phone": ASHA, "date": d, "time": "10:00:00"},
                       headers=h("dental", **{"Idempotency-Key": new_key()})).json()["appointment"]["id"]
    client.post(f"/appointments/{appt}/reschedule", json={"customer_phone": ASHA, "date": d, "time": "11:00:00"},
                headers=h("dental"))
    client.post(f"/appointments/{appt}/cancel", json={"customer_phone": ASHA}, headers=h("dental"))
    client.post("/escalations", json={"reason": "Call me back"}, headers=h("dental", **{"Idempotency-Key": new_key()}))
    client.post("/customers", json={"full_name": "Brand New", "phone": "+919333333333"}, headers=h("dental"))
    client.post("/invoices/email-request", json={"customer_phone": ASHA}, headers=h("dental"))
    client.patch(f"/staff/tickets/{t}", json={"status": "resolved"}, headers=h("dental_staff"))

    actions = [r["action"] for r in audit_rows()]
    assert actions == ["ticket.create", "appointment.book", "appointment.reschedule", "appointment.cancel",
                       "escalation.create", "customer.register", "invoice.email_request",
                       "ticket.status_update"]
    rows = {r["action"]: r for r in audit_rows()}
    assert rows["ticket.create"]["actor_type"] == "ai"
    assert rows["ticket.status_update"]["actor_type"] == "staff"
    assert rows["ticket.status_update"]["details"] == {"from": "open", "to": "resolved"}
    assert rows["appointment.reschedule"]["target_id"] == appt
    assert rows["invoice.email_request"]["details"] == {"invoice_number": "INV-1001"}
    assert all(r["company_id"] == world["dental_id"] for r in audit_rows())


def test_repeated_requests_do_not_repeat_the_audit_record(client, world, h, n8n):
    key = new_key()
    body = {"subject": "Same thing", "description": "Sent twice"}
    client.post("/tickets", json=body, headers=h("dental", **{"Idempotency-Key": key}))
    client.post("/tickets", json=body, headers=h("dental", **{"Idempotency-Key": key}))
    assert len(audit_rows("ticket.create")) == 1


def test_failed_requests_leave_no_audit_record(client, world, h, n8n):
    client.post("/tickets", json={"subject": "Bad customer", "description": "Nobody here",
                                  "customer_phone": "+910000000000"},
                headers=h("dental", **{"Idempotency-Key": new_key()}))
    assert audit_rows() == []


def test_settings_changes_record_before_and_after(client, world, h):
    client.patch("/staff/company", json={"open_hour": 10, "staff_email": "x@y.example"}, headers=h("dental_staff"))
    row = audit_rows("company.settings_update")[0]
    assert row["actor_type"] == "staff" and row["target_type"] == "company"
    assert row["details"] == {"before": {"open_hour": 9, "staff_email": None},
                              "after": {"open_hour": 10, "staff_email": "x@y.example"}}


def test_staff_can_read_their_own_audit_trail_only(client, world, h, n8n):
    make_ticket(client, h, ASHA)
    client.post("/tickets", json={"subject": "Shop question", "description": "From the shop"},
                headers=h("shop", **{"Idempotency-Key": new_key()}))
    mine = client.get("/staff/audit", headers=h("dental_staff")).json()
    assert [e["action"] for e in mine] == ["ticket.create"]
    assert mine[0]["actor_type"] == "ai" and mine[0]["ip"]
    assert len(client.get("/staff/audit", headers=h("shop_staff")).json()) == 1
    assert client.get("/staff/audit", params={"action": "nothing.like.this"},
                      headers=h("dental_staff")).json() == []
    assert client.get("/staff/audit", params={"limit": 0}, headers=h("dental_staff")).status_code == 422
    assert client.get("/staff/audit", headers=h("dental")).status_code == 401  # the AI key may not read it


# ---------- log redaction ----------

@pytest.mark.parametrize("text,must_not_contain,must_contain", [
    ("lookup phone=%2B919000000001 done", "9000000001", "[phone ***01]"),
    ("calling +919000000001 now", "9000000001", "[phone ***01]"),
    ("calling +91 98765 43210 now", "98765", "[phone ***10]"),
    ("calling 9876543210 now", "9876543210", "[phone ***10]"),
    ("mail kanya.r@gmail.com sent", "kanya.r", "k***@gmail.com"),
    ("key jrv_AbCdEf123456789 used", "AbCdEf123456789", "jrv_[hidden]"),
    ("key stf_AbCdEf123456789 used", "AbCdEf123456789", "stf_[hidden]"),
])
def test_redact(text, must_not_contain, must_contain):
    out = redact(text)
    assert must_not_contain not in out and must_contain in out


def test_redact_leaves_normal_text_alone():
    text = "GET /faq/search?q=opening+hours 200 OK in 12 ms, ticket 42, port 8000"
    assert redact(text) == text


def test_log_lines_are_cleaned_everywhere(caplog):
    from app.privacy import install_log_redaction
    install_log_redaction()
    with caplog.at_level(logging.INFO):
        logging.getLogger("anything.at.all").info("customer %s wrote from %s", "+919000000001", "asha@example.com")
    text = caplog.text
    assert "9000000001" not in text and "asha@example.com" not in text
    assert "[phone ***01]" in text and "a***@example.com" in text
