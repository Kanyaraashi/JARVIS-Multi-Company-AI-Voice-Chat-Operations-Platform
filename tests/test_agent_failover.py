"""The AI helpers and the automatic model switching. No real Gemini is called."""
import httpx
import pytest
from google.genai import errors

from app import agent
from app.agent import (ChatSession, EmptyReply, TurnFailed, build_message,
                       build_system_prompt, classify, describe, find_phone,
                       handoff, handoff_message)


def api_error(code):
    return errors.APIError(code, {"error": {"message": f"boom {code}", "status": "X"}})


# ---------- small helpers ----------

@pytest.mark.parametrize("exc,expected", [
    (api_error(503), "retry"), (api_error(500), "retry"), (api_error(504), "retry"),
    (EmptyReply("empty"), "retry"),
    (api_error(429), "next"), (api_error(404), "next"), (TimeoutError("slow"), "next"),
    (RuntimeError("other"), "next"),
])
def test_classify(exc, expected):
    assert classify(exc) == expected


def test_describe():
    assert describe(RuntimeError("bad thing")).startswith("RuntimeError: bad thing")
    assert describe(api_error(503)).startswith("503")


def test_build_message_without_tools_is_unchanged():
    assert build_message("hello", []) == "hello"


def test_build_message_hands_over_tool_results():
    log = [{"call": "GET /tickets/7", "sent": "{}", "ok": True, "result": '{"status": "open"}'}]
    text = build_message("status of ticket 7?", log)
    assert "GET /tickets/7" in text and '"status": "open"' in text
    assert "Do not repeat actions that already succeeded" in text
    assert text.endswith("status of ticket 7?")


def test_build_message_keeps_only_the_last_eight_calls():
    log = [{"call": f"GET /x/{i}", "sent": "{}", "ok": True, "result": "r"} for i in range(12)]
    text = build_message("hi", log)
    assert "GET /x/11" in text and "GET /x/4" in text and "GET /x/3 " not in text


@pytest.mark.parametrize("text,expected", [
    ("my number is +919000000001 thanks", "+919000000001"),
    ("call 98765 43210 please", "+919876543210"),
    ("it is 9876543210", "+919876543210"),
    ("no number here", None),
    ("order 12345", None),
])
def test_find_phone(text, expected):
    assert find_phone(text) == expected


def test_system_prompt_contains_company_and_rules():
    prompt = build_system_prompt({
        "name": "Smile Dental", "agent_name": "Maya", "instructions": "Be kind",
        "greeting": "Hi", "default_language": "en", "timezone": "Asia/Kolkata"})
    assert "Smile Dental" in prompt and "Maya" in prompt
    assert "customer_confirmed" in prompt and "NEVER say amounts" in prompt


def test_handoff_messages():
    assert "technical trouble" in handoff_message(None) and "could not record" in handoff_message(None)
    assert "passed your request" in handoff_message({"within_business_hours": True})
    assert "office is closed" in handoff_message({"within_business_hours": False})


# ---------- handoff when every model is down ----------

def test_handoff_records_an_escalation(client, world, n8n, monkeypatch):
    from conftest import KEYS
    monkeypatch.setattr(agent.httpx, "post",
                        lambda url, headers=None, json=None, timeout=None:
                        client.post(url.replace(agent.API_BASE, ""), headers=headers, json=json))
    first = handoff(KEYS["dental"], "I need my bill", "+919000000001", "sess")
    again = handoff(KEYS["dental"], "I need my bill", "+919000000001", "sess")
    assert first["ticket"]["priority"] == "urgent"
    assert again["already_existed"] is True  # same chat, same message: one ticket only
    unknown = handoff(KEYS["dental"], "different text", "+910000000000", "sess")
    assert unknown["ticket"]["customer_id"] is None  # unknown number still gets recorded


def test_handoff_when_api_is_unreachable_or_refuses(monkeypatch):
    def down(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(agent.httpx, "post", down)
    assert handoff("key", "text", None, "s") is None
    monkeypatch.setattr(agent.httpx, "post",
                        lambda *a, **k: httpx.Response(401, request=httpx.Request("POST", "http://x")))
    assert handoff("key", "text", "+919000000001", "s") is None


# ---------- the automatic switching ----------

class FakeReply:
    def __init__(self, text):
        self.text = text


class FakeChat:
    def __init__(self, behaviour, calls, model, hook=None):
        self.behaviour, self.calls, self.model, self.hook = behaviour, calls, model, hook

    def send_message(self, message):
        self.calls.append((self.model, message))
        if self.hook:
            self.hook(self.model)  # lets a test pretend a tool ran during this attempt
        step = self.behaviour.pop(0) if len(self.behaviour) > 1 else self.behaviour[0]
        if isinstance(step, Exception):
            raise step
        return FakeReply(step)


class FakeClient:
    """behaviours maps model name to a list of results: a string answer or an exception."""

    def __init__(self, behaviours, hook=None):
        self.behaviours, self.calls, self.created, self.hook = behaviours, [], [], hook
        self.chats = self

    def create(self, model, config, history):
        self.created.append((model, history))
        return FakeChat(self.behaviours[model], self.calls, model, self.hook)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(agent, "RETRY_DELAY", 0)
    monkeypatch.setattr(agent.time, "sleep", lambda s: None)


def session(behaviours, tool_log=None, models=None, hook=None):
    client = FakeClient(behaviours, hook)
    s = ChatSession(client, "system", [], tool_log if tool_log is not None else [],
                    models or list(behaviours), "NONE")
    return s, client


def test_normal_answer_uses_the_first_model():
    s, client = session({"a": ["Hello!"], "b": ["unused"]})
    assert s.send("hi") == ("Hello!", "a")
    assert [c[0] for c in client.calls] == ["a"]


def test_busy_model_is_retried_once_then_succeeds():
    s, client = session({"a": [api_error(503), "Now I can answer"], "b": ["unused"]})
    assert s.send("hi") == ("Now I can answer", "a")
    assert len(client.calls) == 2


def test_busy_twice_switches_to_the_next_model_in_the_same_turn():
    s, client = session({"a": [api_error(503)], "b": ["Fallback answer"]})
    answer, used = s.send("hi")
    assert (answer, used) == ("Fallback answer", "b")
    assert [c[0] for c in client.calls] == ["a", "a", "b"]


def test_hard_error_switches_immediately_without_retry():
    s, client = session({"a": [api_error(404)], "b": ["Fallback answer"]})
    assert s.send("hi")[1] == "b"
    assert [c[0] for c in client.calls] == ["a", "b"]


def test_empty_reply_counts_as_a_failure():
    s, client = session({"a": ["   "], "b": ["Real answer"]})
    assert s.send("hi") == ("Real answer", "b")


def test_failed_model_is_skipped_for_a_while():
    s, client = session({"a": [api_error(404)], "b": ["one", "two"]})
    s.send("first")
    s.send("second")
    assert [c[0] for c in client.calls] == ["a", "b", "b"]  # a was not tried again


def test_everything_down_raises_turnfailed():
    s, _ = session({"a": [api_error(503)], "b": [api_error(429)]})
    with pytest.raises(TurnFailed) as info:
        s.send("hi")
    assert "429" in info.value.reason


def test_the_next_model_receives_the_tool_results_and_the_history():
    log = []

    def tool_ran(model):
        if model == "a" and not log:
            log.append({"call": "GET /tickets/7", "sent": "{}", "ok": True,
                        "result": '{"status": "open"}'})

    s, client = session({"a": ["First answer", api_error(404)], "b": ["Second answer"]},
                        tool_log=log, hook=tool_ran)
    s.send("hello")                      # a answers normally; the history now has 2 messages
    log.clear()
    answer, used = s.send("status of ticket 7?")   # a runs the tool, then fails
    assert (answer, used) == ("Second answer", "b")
    handed = client.calls[-1][1]
    assert "GET /tickets/7" in handed
    assert "Customer's last message: status of ticket 7?" in handed
    model, history = client.created[-1]
    assert model == "b" and len(history) == 2    # b also got the earlier chat as plain text


def test_time_budget_stops_the_turn(monkeypatch):
    monkeypatch.setattr(agent, "TURN_BUDGET", -1)
    s, client = session({"a": ["never used"]})
    with pytest.raises(TurnFailed):
        s.send("hi")
    assert client.calls == []


def test_test_switch_discards_the_first_models_answer_after_tools(monkeypatch):
    monkeypatch.setattr(agent, "TEST_FAIL_AFTER_TOOLS", True)
    log = []

    def tool_ran(model):
        if model == "a":
            log.append({"call": "GET /x", "sent": "{}", "ok": True, "result": "r"})

    s, client = session({"a": ["answer"], "b": ["Fallback answer"]}, tool_log=log, hook=tool_ran)
    assert s.send("hi") == ("Fallback answer", "b")
