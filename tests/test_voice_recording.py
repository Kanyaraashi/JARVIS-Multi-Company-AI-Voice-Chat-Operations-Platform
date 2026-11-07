"""Saving a call: it reaches the API, or it is kept safely, and the caller is never dropped."""
import asyncio
import json

import httpx
import pytest

from app.models import CallRecord
from app.voice import recorder as rec
from app.voice import spool as spool_cli
from app.voice import worker
from conftest import AdminSession, KEYS

ASHA = "+919000000001"


def finished_call(room="call-rec-1", **kw) -> rec.CallRecorder:
    r = rec.CallRecorder(room, "inbound", ASHA, {"stack": "test"}, clock=lambda: 1075.0)
    r.started = 1000.0
    r.on_message("assistant", "Hello, Smile Dental.", {})
    r.on_message("user", "My number is +919876543210", {"stopped_speaking_at": 1010.0, "end_of_turn_delay": 0.3})
    r.on_message("assistant", "Thanks.", {"started_speaking_at": 1011.0, "llm_node_ttft": 0.5, "tts_node_ttfb": 0.2})
    r.tool_finished("lookup_customer", {"ok": True, "data": {}})
    return r


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(rec.time, "sleep", lambda s: None)


# ---------- the recorder's own record ----------

def test_the_payload_has_what_the_api_needs_and_masks_personal_details():
    p = finished_call().payload()
    assert p["outcome"] == "completed" and p["direction"] == "inbound"
    assert "9876543210" not in json.dumps(p) and "[phone ***10]" in p["transcript"][1]["text"]
    assert p["latency_turns"][0]["total_ms"] == 1000 and p["tools_used"] == [{"name": "lookup_customer", "ok": True}]


def test_outcomes_are_decided_honestly():
    r = rec.CallRecorder("call-o", "web", None, {})
    assert r.outcome() == "abandoned"
    r.on_message("assistant", "Hello", {})
    assert r.outcome() == "abandoned"
    r.on_message("user", "Hi", {})
    assert r.outcome() == "completed"
    r.tool_finished("transfer_to_human", {"ok": False})
    assert r.outcome() == "completed"
    r.mark_failed()
    assert r.outcome() == "failed"
    r.tool_finished("transfer_to_human", {"ok": True})
    assert r.outcome() == "handoff"


def test_a_tool_result_without_ok_true_is_never_counted_as_success():
    r = rec.CallRecorder("call-t", "web", None, {})
    for result in ({"ok": "yes"}, {"ok": 1}, {}, None, "ok"):
        r.tool_finished("x", result)
    assert [t["ok"] for t in r.tools] == [False] * 5


def test_empty_and_unknown_messages_are_ignored():
    r = rec.CallRecorder("call-e", "web", None, {})
    r.on_message("user", "   ", {})
    r.on_message("system", "secret", {})
    r.on_message("assistant", None, {})
    assert r.lines == []


# ---------- the recorder's payload really passes the API's checks ----------

def test_a_real_recorder_payload_is_accepted_by_the_api(client, world, monkeypatch):
    monkeypatch.setattr(rec.httpx, "post", lambda url, json=None, headers=None, timeout=None: client.post(url.replace("http://127.0.0.1:8000", ""), json=json, headers=headers))
    ok, reason = rec.send("http://127.0.0.1:8000", KEYS["dental"], finished_call().payload())
    assert (ok, reason) == (True, "saved")
    with AdminSession() as db:
        row = db.query(CallRecord).one()
        assert row.customer_id == world["asha_id"] and row.turn_count == 1 and row.duration_seconds == 75


# ---------- sending, retrying and the safety net ----------

class FakePost:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0
        self.answers_last = answers[-1]

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        answer = self.answers.pop(0) if self.answers else self.answers_last
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer, request=httpx.Request("POST", url), text="body")


def test_a_temporary_failure_is_retried_until_it_works(monkeypatch, fast):
    fake = FakePost(503, httpx.ConnectError("down"), 200)
    monkeypatch.setattr(rec.httpx, "post", fake)
    assert rec.send("http://api", "k", {"room_name": "r"}) == (True, "saved") and fake.calls == 3


def test_a_rejected_record_is_not_retried(monkeypatch, fast):
    fake = FakePost(422)
    monkeypatch.setattr(rec.httpx, "post", fake)
    ok, reason = rec.send("http://api", "k", {"room_name": "r"})
    assert ok is False and "422" in reason and fake.calls == 1


def test_giving_up_reports_the_reason(monkeypatch, fast):
    monkeypatch.setattr(rec.httpx, "post", FakePost(*[httpx.ConnectError("down")] * 3))
    ok, reason = rec.send("http://api", "k", {"room_name": "r"})
    assert ok is False and "not reachable" in reason


def test_an_unsaved_call_is_kept_on_disk_without_any_api_key(tmp_path, monkeypatch, fast):
    monkeypatch.setenv("VOICE_SPOOL_DIR", str(tmp_path))
    monkeypatch.setattr(rec.httpx, "post", FakePost(*[httpx.ConnectError("down")] * 3))
    result = asyncio.run(worker.save_call(finished_call(), "smile-dental", "jrv_SECRET_KEY_123", "http://api"))
    assert "NOT saved" in result
    files = list(tmp_path.glob("*.json"))
    assert [f.name for f in files] == ["smile-dental__call-rec-1.json"]
    text = files[0].read_text()
    assert "jrv_SECRET_KEY_123" not in text and "9876543210" not in text


def test_spooled_calls_are_sent_later_and_removed(tmp_path, monkeypatch, capsys, client, world):
    monkeypatch.setenv("VOICE_SPOOL_DIR", str(tmp_path))
    monkeypatch.setenv("JARVIS_KEY_SMILE_DENTAL", KEYS["dental"])
    rec.spool("smile-dental", finished_call().payload(), "test")
    rec.spool("ghost-co", finished_call(room="call-rec-2").payload(), "test")  # no key in .env
    monkeypatch.setattr(rec.httpx, "post", lambda url, json=None, headers=None, timeout=None: client.post(url.replace("http://127.0.0.1:8000", ""), json=json, headers=headers))
    spool_cli.main()
    out = capsys.readouterr().out
    assert "1 of 2 saved" in out and "no key for company ghost-co" in out
    assert [f.name for f in tmp_path.glob("*.json")] == ["ghost-co__call-rec-2.json"]
    with AdminSession() as db:
        assert db.query(CallRecord).count() == 1


def test_with_nothing_spooled_the_command_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VOICE_SPOOL_DIR", str(tmp_path / "nothing"))
    spool_cli.main()
    assert "Nothing waiting" in capsys.readouterr().out


def test_a_failed_call_asks_staff_to_call_back(monkeypatch, fast):
    r = finished_call(room="call-rec-3")
    r.mark_failed()
    asked = {}
    monkeypatch.setattr(rec.httpx, "post", FakePost(200))
    monkeypatch.setattr(worker, "handoff", lambda key, text, phone, session: asked.update(text=text, phone=phone, session=session) or {"ok": 1})
    result = asyncio.run(worker.save_call(r, "smile-dental", "k", "http://api"))
    assert "callback request recorded" in result
    assert asked == {"text": r.last_user_text(), "phone": ASHA, "session": "call-rec-3"}


def test_a_normal_call_does_not_trigger_a_callback(monkeypatch, fast):
    monkeypatch.setattr(rec.httpx, "post", FakePost(200))
    monkeypatch.setattr(worker, "handoff", lambda *a: pytest.fail("no callback expected"))
    assert "saved (completed)" in asyncio.run(worker.save_call(finished_call(), "smile-dental", "k", "http://api"))


def test_a_failed_callback_is_reported_not_hidden(monkeypatch, fast):
    r = finished_call()
    r.mark_failed()
    monkeypatch.setattr(rec.httpx, "post", FakePost(200))
    monkeypatch.setattr(worker, "handoff", lambda *a: None)
    assert "could NOT be recorded" in asyncio.run(worker.save_call(r, "smile-dental", "k", "http://api"))


from app.voice.recorder import CallRecorder  # noqa: E402


def test_filler_and_switch_notes_are_attached_to_the_turn_they_belong_to():
    rec = CallRecorder("call-n", "web", None, {})
    rec.on_message("user", "Hours?", {"stopped_speaking_at": 10.0, "end_of_turn_delay": 0.3})
    rec.note_first_token(8000)
    rec.note_first_token(100)          # a later round does not replace the first
    rec.note_filler()
    rec.note_switch("a", "b", "too slow")
    rec.on_message("assistant", "One moment please. We open at nine.", {"started_speaking_at": 12.6, "llm_node_ttft": 2.5})
    rec.on_message("user", "Thanks", {"stopped_speaking_at": 20.0})
    rec.on_message("assistant", "Welcome.", {"started_speaking_at": 20.8})
    first, second = rec.turns
    assert first["llm_real_ms"] == 8000 and first["filler"] is True and first["switched"] is True
    assert "llm_real_ms" not in second and "filler" not in second and "switched" not in second


def test_the_sorry_message_never_counts_as_answering_the_caller():
    r = CallRecorder("call-s", "web", None, {})
    r.not_answers.add("Sorry, technical trouble.")
    r.on_message("user", "Hours?", {})
    r.on_error()
    r.on_message("assistant", "Sorry, technical trouble.", {})
    assert r.unanswered() and r.outcome() == "failed"
    assert r.lines[-1]["text"] == "Sorry, technical trouble."   # still in the transcript
