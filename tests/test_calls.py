"""Step 24: call records. Saved once, masked, private to the company, honest about outcomes."""
from datetime import datetime, timedelta, timezone

from conftest import AdminSession
from app.models import AuditLog, CallRecord


def call(room="call-abc123", **changes):
    started = datetime.now(timezone.utc) - timedelta(minutes=3)
    body = {
        "room_name": room,
        "direction": "inbound",
        "caller_phone": "+919000000001",
        "started_at": started.isoformat(),
        "ended_at": (started + timedelta(seconds=95)).isoformat(),
        "outcome": "completed",
        "transcript": [
            {"role": "assistant", "text": "Hello, Smile Dental."},
            {"role": "user", "text": "What are your opening hours?"},
            {"role": "assistant", "text": "We are open 9 to 6."},
        ],
        "tools_used": [{"name": "search_company_faq", "ok": True}],
        "latency_turns": [
            {"total_ms": 900, "listen_ms": 300, "think_ms": 400, "speak_ms": 200, "source": "measured"},
            {"total_ms": 1700, "listen_ms": 300, "think_ms": 1200, "speak_ms": 200, "source": "measured"},
        ],
        "providers": {"stt": "deepgram", "llm": "gemini", "tts": "deepgram"},
    }
    body.update(changes)
    return body


def post(client, h, body, who="dental"):
    return client.post("/calls", json=body, headers=h(who))


# ---------- saving ----------

def test_a_finished_call_is_saved_with_duration_and_turns(client, world, h):
    r = post(client, h, call())
    assert r.status_code == 200
    data = r.json()
    assert data["already_existed"] is False
    assert data["duration_seconds"] == 95 and data["turn_count"] == 1
    assert data["outcome"] == "completed"


def test_sending_the_same_call_twice_saves_it_once(client, world, h):
    first = post(client, h, call()).json()
    second = post(client, h, call()).json()
    assert second["already_existed"] is True and second["id"] == first["id"]
    with AdminSession() as db:
        assert db.query(CallRecord).count() == 1
        assert db.query(AuditLog).filter(AuditLog.action == "call.record").count() == 1


def test_the_same_room_name_in_two_companies_is_two_records(client, world, h):
    post(client, h, call(), "dental")
    r = post(client, h, call(), "shop")
    assert r.json()["already_existed"] is False
    with AdminSession() as db:
        assert db.query(CallRecord).count() == 2


def test_the_caller_is_linked_to_the_customer_of_the_same_company_only(client, world, h):
    post(client, h, call())  # +919000000001 is Asha in dental and Dev in shop
    post(client, h, call(room="call-shop-1"), "shop")
    post(client, h, call(room="call-unknown", caller_phone="+911111111111"))
    with AdminSession() as db:
        rows = {r.room_name: r for r in db.query(CallRecord)}
        assert rows["call-abc123"].customer_id == world["asha_id"]
        assert rows["call-shop-1"].customer_id == world["dev_id"]
        assert rows["call-unknown"].customer_id is None


def test_an_anonymous_caller_is_still_recorded_without_a_number(client, world, h):
    r = post(client, h, call(caller_phone="anonymous"))
    assert r.status_code == 200
    with AdminSession() as db:
        assert db.query(CallRecord).one().caller_phone is None


def test_personal_details_in_the_transcript_are_masked(client, world, h):
    body = call(transcript=[
        {"role": "user", "text": "My number is +919876543210 and my email is asha.rao@example.com"},
    ])
    post(client, h, body)
    with AdminSession() as db:
        text = db.query(CallRecord).one().transcript[0]["text"]
    assert "9876543210" not in text and "asha.rao" not in text
    assert "[phone ***10]" in text and "a***@example.com" in text


def test_saving_a_call_leaves_an_audit_entry_without_the_transcript(client, world, h):
    post(client, h, call())
    with AdminSession() as db:
        entry = db.query(AuditLog).filter(AuditLog.action == "call.record").one()
        assert entry.actor_type == "ai" and entry.target_type == "call"
        assert entry.details == {"outcome": "completed", "duration_seconds": 95}


# ---------- honest outcomes and bad input ----------

def test_a_handoff_needs_a_successful_transfer(client, world, h):
    assert post(client, h, call(outcome="handoff")).status_code == 422
    failed = call(outcome="handoff", tools_used=[{"name": "transfer_to_human", "ok": False}])
    assert post(client, h, failed).status_code == 422
    good = call(outcome="handoff", tools_used=[{"name": "transfer_to_human", "ok": True}])
    assert post(client, h, good).status_code == 200


def test_an_abandoned_call_cannot_contain_caller_speech(client, world, h):
    assert post(client, h, call(outcome="abandoned")).status_code == 422
    silent = call(outcome="abandoned", transcript=[{"role": "assistant", "text": "Hello"}], latency_turns=[])
    assert post(client, h, silent).status_code == 200


def test_impossible_times_are_rejected(client, world, h):
    now = datetime.now(timezone.utc)
    backwards = call(started_at=now.isoformat(), ended_at=(now - timedelta(seconds=5)).isoformat())
    assert post(client, h, backwards).status_code == 422
    too_long = call(started_at=(now - timedelta(hours=8)).isoformat(), ended_at=now.isoformat())
    assert post(client, h, too_long).status_code == 422
    future = call(started_at=(now + timedelta(hours=2)).isoformat(), ended_at=(now + timedelta(hours=3)).isoformat())
    assert post(client, h, future).status_code == 422
    naive = call(started_at="2026-11-01T10:00:00", ended_at="2026-11-01T10:05:00")
    assert post(client, h, naive).status_code == 422


def test_bad_fields_are_rejected(client, world, h):
    assert post(client, h, call(room="x")).status_code == 422
    assert post(client, h, call(room="bad room!")).status_code == 422
    assert post(client, h, call(direction="fax")).status_code == 422
    assert post(client, h, call(outcome="great")).status_code == 422
    assert post(client, h, call(latency_turns=[{"total_ms": -5}])).status_code == 422
    assert post(client, h, call(transcript=[{"role": "user", "text": "x" * 2001}])).status_code == 422


def test_saving_needs_the_ai_key_not_a_staff_key_or_nothing(client, world):
    body = call()
    assert client.post("/calls", json=body).status_code == 401
    assert client.post("/calls", json=body, headers={"X-API-Key": "stf_dental_test_key"}).status_code in (401, 403)


# ---------- staff views ----------

def staff(who="dental_staff"):
    return {"X-API-Key": {"dental_staff": "stf_dental_test_key", "shop_staff": "stf_shop_test_key"}[who]}


def test_staff_see_their_calls_newest_first_with_customer_name(client, world, h):
    post(client, h, call(room="call-1"))
    post(client, h, call(room="call-2", caller_phone="+911111111111"))
    r = client.get("/staff/calls", headers=staff())
    assert r.status_code == 200
    rows = r.json()
    assert [c["room_name"] for c in rows] == ["call-2", "call-1"]
    assert rows[1]["customer_name"] == "Asha Rao" and rows[0]["customer_name"] is None
    assert "transcript" not in rows[0]
    assert rows[1]["latency"]["p50_ms"] == 900 and rows[1]["latency"]["p95_ms"] == 1700


def test_staff_can_filter_calls_by_outcome(client, world, h):
    post(client, h, call(room="call-1"))
    post(client, h, call(room="call-2", outcome="failed"))
    rows = client.get("/staff/calls?outcome=failed", headers=staff()).json()
    assert [c["room_name"] for c in rows] == ["call-2"]
    assert client.get("/staff/calls?outcome=nonsense", headers=staff()).status_code == 422


def test_staff_never_see_another_companys_calls(client, world, h):
    post(client, h, call(room="call-dental"), "dental")
    post(client, h, call(room="call-shop"), "shop")
    dental = client.get("/staff/calls", headers=staff("dental_staff")).json()
    shop = client.get("/staff/calls", headers=staff("shop_staff")).json()
    assert [c["room_name"] for c in dental] == ["call-dental"]
    assert [c["room_name"] for c in shop] == ["call-shop"]
    shop_call_id = shop[0]["id"]
    assert client.get(f"/staff/calls/{shop_call_id}", headers=staff("dental_staff")).status_code == 404


def test_the_ai_key_cannot_read_calls_back(client, world, h):
    post(client, h, call())
    assert client.get("/staff/calls", headers=h("dental")).status_code in (401, 403)


def test_call_detail_shows_the_masked_transcript_and_tools(client, world, h):
    post(client, h, call())
    call_id = client.get("/staff/calls", headers=staff()).json()[0]["id"]
    detail = client.get(f"/staff/calls/{call_id}", headers=staff()).json()
    assert [l["role"] for l in detail["transcript"]] == ["assistant", "user", "assistant"]
    assert detail["tools_used"] == [{"name": "search_company_faq", "ok": True}]
    assert detail["providers"]["stt"] == "deepgram"
    assert client.get("/staff/calls/99999", headers=staff()).status_code == 404


# ---------- the latency report ----------

def test_latency_report_combines_recent_calls_of_one_company(client, world, h):
    post(client, h, call(room="call-1"))
    post(client, h, call(room="call-2", latency_turns=[{"total_ms": 2500, "listen_ms": 300, "think_ms": 2000, "speak_ms": 200}]))
    post(client, h, call(room="call-shop", latency_turns=[{"total_ms": 9000}]), "shop")
    r = client.get("/staff/calls/latency", headers=staff()).json()
    assert r["calls_included"] == 2 and r["turns"] == 3
    assert r["max_ms"] == 2500 and r["p50_ms"] == 1700
    assert r["within_target_pct"] == 33  # only 900 ms of 900, 1700, 2500 is within 1500
    relaxed = client.get("/staff/calls/latency?target_ms=2000", headers=staff()).json()
    assert relaxed["within_target_pct"] == 67


def test_latency_report_with_no_calls_says_so(client, world):
    r = client.get("/staff/calls/latency", headers=staff()).json()
    assert r["calls_included"] == 0 and r["turns"] == 0 and r["p50_ms"] is None


def test_latency_report_validates_its_inputs(client, world):
    assert client.get("/staff/calls/latency?calls=0", headers=staff()).status_code == 422
    assert client.get("/staff/calls/latency?target_ms=50", headers=staff()).status_code == 422
