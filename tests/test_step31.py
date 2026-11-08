"""Step 31: real client IP behind a proxy, alerts, privacy tools."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app import retention, watchdog
from app.audit import client_ip
from app.models import AuditLog, Appointment, CallRecord, Customer, SupportTicket, TicketUpdate, WorkflowEvent, Invoice
from conftest import AdminSession

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def req(peer="10.0.0.5", xff=None):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


# ---- client_ip -------------------------------------------------------------------------
def test_header_is_ignored_unless_a_proxy_is_trusted(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_COUNT", raising=False)
    assert client_ip(req(xff="1.2.3.4")) == "10.0.0.5"


def test_one_trusted_proxy_uses_the_rightmost_entry_so_faking_does_not_work(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    assert client_ip(req(xff="6.6.6.6, 203.0.113.9")) == "203.0.113.9"      # the caller wrote 6.6.6.6 himself


def test_bad_values_fall_back_to_the_real_peer(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    assert client_ip(req(xff="not-an-ip")) == "10.0.0.5"
    assert client_ip(req(xff=None)) == "10.0.0.5"
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "abc")
    assert client_ip(req(xff="1.2.3.4")) == "10.0.0.5"
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "3")
    assert client_ip(req(xff="1.2.3.4")) == "10.0.0.5"                       # fewer hops than expected


def test_two_users_behind_the_proxy_no_longer_share_a_failure_limit(client, world, monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    for _ in range(12):
        client.get("/staff/company", headers={"X-API-Key": "stf_wrong", "X-Forwarded-For": "198.51.100.7"})
    blocked = client.get("/staff/company", headers={"X-API-Key": "stf_wrong", "X-Forwarded-For": "198.51.100.7"})
    other = client.get("/staff/company", headers={"X-API-Key": "stf_wrong", "X-Forwarded-For": "198.51.100.8"})
    assert blocked.status_code == 429 and other.status_code == 401


# ---- watchdog --------------------------------------------------------------------------
def test_no_problems_means_no_message():
    msg, state = watchdog.decide([], {}, NOW)
    assert msg is None and state == {}


def test_problem_is_sent_once_then_reminded_then_recovery_announced():
    msg, st = watchdog.decide(["API down"], {}, NOW)
    assert "API down" in msg
    assert watchdog.decide(["API down"], st, NOW + timedelta(minutes=5))[0] is None       # no spam
    assert watchdog.decide(["API down"], st, NOW + timedelta(hours=7))[0] is not None      # reminder
    assert watchdog.decide(["API down", "n8n"], st, NOW + timedelta(minutes=5))[0] is not None  # new problem
    msg2, st2 = watchdog.decide([], st, NOW + timedelta(minutes=10))
    assert "recovered" in msg2 and st2["fingerprint"] == ""


def test_collect_problems_finds_failed_calls_stuck_events_and_spool(world):
    with AdminSession() as db:
        db.add(CallRecord(company_id=world["dental_id"], room_name="call-x", direction="inbound",
                          started_at=NOW - timedelta(minutes=5), ended_at=NOW, duration_seconds=10, outcome="failed",
                          turn_count=1, transcript=[], tools_used=[], latency_turns=[], providers={}))
        db.add(WorkflowEvent(company_id=world["shop_id"], event_type="ticket_created", payload={}, status="failed",
                             created_at=NOW - timedelta(hours=1)))
        db.commit()
        problems = watchdog.collect_problems(False, "no connection", db, 2, NOW)
    text = " ".join(problems)
    assert "API is not answering" in text and "smile-dental" in text and "shopeasy" in text and "2 call record" in text


def test_run_once_sends_the_alert_and_remembers_it(tmp_path, world):
    sent = []

    class R:  status_code = 200

    def get(url, timeout=None):
        raise OSError("down")

    def post(url, json=None, timeout=None):
        sent.append(json); return R()

    import os
    env = {**os.environ, "ALERT_WEBHOOK_URL": "https://hooks.example/x", "VOICE_SPOOL_DIR": str(tmp_path / "none")}
    first = watchdog.run_once(env, get, post, NOW, tmp_path / "state.json")
    second = watchdog.run_once(env, get, post, NOW + timedelta(minutes=5), tmp_path / "state.json")
    assert first and second and len(sent) == 1 and "not answering" in sent[0]["text"]


def test_failed_delivery_is_retried_next_time(tmp_path, world):
    class Bad:  status_code = 500
    calls = []
    import os
    env = {**os.environ, "ALERT_WEBHOOK_URL": "https://hooks.example/x", "VOICE_SPOOL_DIR": str(tmp_path / "none")}
    get = lambda url, timeout=None: (_ for _ in ()).throw(OSError("down"))
    post = lambda url, json=None, timeout=None: (calls.append(1), Bad())[1]
    watchdog.run_once(env, get, post, NOW, tmp_path / "s.json")
    watchdog.run_once(env, get, post, NOW + timedelta(minutes=5), tmp_path / "s.json")
    assert len(calls) == 2


# ---- retention -------------------------------------------------------------------------
def seed_private_data(world):
    with AdminSession() as db:
        asha = db.get(Customer, world["asha_id"])
        old = NOW - timedelta(days=200)
        db.add(CallRecord(company_id=world["dental_id"], room_name="call-old", direction="inbound", caller_phone=asha.phone,
                          customer_id=asha.id, started_at=old, ended_at=old, duration_seconds=5, outcome="completed",
                          turn_count=1, transcript=[{"role": "user", "text": "my tooth hurts"}], tools_used=[{"name": "x"}],
                          latency_turns=[{"llm_real_ms": 900}], providers={}))
        db.add(CallRecord(company_id=world["dental_id"], room_name="call-new", direction="inbound", caller_phone="+910000",
                          started_at=NOW, ended_at=NOW, duration_seconds=5, outcome="completed", turn_count=1,
                          transcript=[{"role": "user", "text": "hello"}], tools_used=[], latency_turns=[], providers={}))
        t = SupportTicket(company_id=world["dental_id"], customer_id=asha.id, subject="Pain", description="Asha has pain")
        db.add(t); db.flush()
        db.add(TicketUpdate(company_id=world["dental_id"], ticket_id=t.id, old_status="open", new_status="open", note="called her"))
        db.commit()


def test_clean_scrubs_only_old_calls_and_keeps_numbers_for_reports(world):
    seed_private_data(world)
    with AdminSession() as db:
        assert retention.clean_calls(db, 90, NOW, dry_run=True) == 1
        assert db.scalar(select(CallRecord).where(CallRecord.room_name == "call-old")).transcript
        assert retention.clean_calls(db, 90, NOW) == 1
        assert retention.clean_calls(db, 90, NOW) == 0                              # nothing left to do
    with AdminSession() as db:
        old = db.scalar(select(CallRecord).where(CallRecord.room_name == "call-old"))
        new = db.scalar(select(CallRecord).where(CallRecord.room_name == "call-new"))
        assert old.transcript == [] and old.caller_phone is None and old.latency_turns == [{"llm_real_ms": 900}]
        assert new.transcript and new.caller_phone == "+910000"


def test_erase_removes_one_customer_everywhere_but_keeps_invoices_and_other_companies(world):
    seed_private_data(world)
    with AdminSession() as db:
        from app.models import Company
        dental = db.get(Company, world["dental_id"])
        result = retention.erase_customer(db, dental, "+91 90000 00001")
        assert result["tickets"] == 1 and result["calls"] == 1
    with AdminSession() as db:
        asha = db.get(Customer, world["asha_id"])
        assert asha.full_name == "Erased customer" and asha.email is None and asha.phone.startswith("erased-")
        t = db.scalar(select(SupportTicket))
        assert t.description == "[erased]" and db.scalar(select(TicketUpdate)).note is None
        assert db.scalar(select(Invoice)).invoice_number == "INV-1001"
        dev = db.get(Customer, world["dev_id"])                                      # same phone, other company
        assert dev.full_name == "Dev Shop" and dev.email == "dev@example.com"
        assert db.scalar(select(AuditLog).where(AuditLog.action == "customer.erase"))


def test_erase_unknown_number_and_short_clean_window_are_refused(world, capsys):
    assert retention.main(["erase", "smile-dental", "+910000000000"]) == 1
    assert retention.main(["clean", "--days", "3"]) == 2


# ---- shipped files ---------------------------------------------------------------------
def test_step31_files_exist_and_hold_no_secrets():
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[1]
    for name in ("deploy/backup.sh", "deploy/restore_test.sh", ".github/workflows/ci.yml", "loadtest/load_test.py"):
        text = (root / name).read_text()
        assert not re.search(r"\b(jrv|stf)_[A-Za-z0-9]{20,}", text), name
    assert "-pbkdf2" in (root / "deploy/backup.sh").read_text()
    assert "alembic upgrade head" in (root / ".github/workflows/ci.yml").read_text()
    assert 'TRUSTED_PROXY_COUNT: "1"' in (root / "docker-compose.proxy.yml").read_text()


def test_load_test_summary_math():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("lt", pathlib.Path(__file__).resolve().parents[1] / "loadtest/load_test.py")
    lt = importlib.util.module_from_spec(spec); spec.loader.exec_module(lt)
    s = lt.summarize([(200, 100), (200, 300), (429, 5), (500, 50), (0, 10)])
    assert s["requests"] == 5 and s["ok"] == 2 and s["rate_limited"] == 1 and s["errors"] == 2 and s["error_pct"] == 40.0
