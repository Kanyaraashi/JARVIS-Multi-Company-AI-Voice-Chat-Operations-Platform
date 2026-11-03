"""Steps 22 and 24 together: a real LiveKit AgentSession, our real tools, our real API.

Only the AI model is replaced by a script (and there is no audio). This proves that the
tools are offered to the model correctly, that they reach the API with the right company's
key, that nothing is booked without confirmation, and that the call record is right.
"""
import asyncio
import json

import pytest
from livekit.agents import AgentSession
from livekit.agents.llm import ChatChunk, ChoiceDelta, FunctionToolCall, LLM, LLMStream
from livekit.agents.llm.tool_context import FunctionTool

from app import agent_tools
from app.voice import tools as voice_tools
from app.voice.prompt import VOICE_RULES, build_voice_prompt
from app.voice.recorder import CallRecorder
from app.voice.worker import JarvisAgent, wire_events
from conftest import KEYS

ASHA = "+919000000001"


class ScriptedStream(LLMStream):
    async def _run(self) -> None:
        step = self._llm.script(self._chat_ctx)
        self._llm.seen_tools = [t.info.name for t in self._tools if hasattr(t, "info")]
        if step[0] == "text":
            delta = ChoiceDelta(role="assistant", content=step[1])
        else:
            call = FunctionToolCall(name=step[1], arguments=json.dumps(step[2]), call_id=f"call_{len(self._chat_ctx.items)}")
            delta = ChoiceDelta(role="assistant", tool_calls=[call])
        self._event_ch.send_nowait(ChatChunk(id="x", delta=delta))


class ScriptedLLM(LLM):
    def __init__(self, script):
        super().__init__()
        self.script = script
        self.seen_tools = []

    def chat(self, *, chat_ctx, tools=None, conn_options=None, **kwargs):
        from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
        return ScriptedStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options or DEFAULT_API_CONNECT_OPTIONS)


def last_is_tool_output(ctx) -> bool:
    return ctx.items[-1].type == "function_call_output"


@pytest.fixture
def api(client, world, n8n, monkeypatch):
    sent = []

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        sent.append({"method": method, "path": url.replace(agent_tools.API_BASE, ""), "key": headers["X-API-Key"]})
        return client.request(method, url.replace(agent_tools.API_BASE, ""), params=params, json=json, headers=headers)

    monkeypatch.setattr(agent_tools.httpx, "request", fake_request)
    return sent


def run_call(script, messages, key="dental"):
    """Plays a call with the given caller messages. Returns (recorder, scripted llm)."""
    recorder = CallRecorder("call-test-1", "inbound", ASHA, {"stack": "test"})
    llm = ScriptedLLM(script)

    async def go():
        session = AgentSession(llm=llm)
        wire_events(session, recorder, hang_up=lambda message: asyncio.sleep(0))
        agent = JarvisAgent(
            "You are a test agent.", voice_tools.build_tools(KEYS[key], "session-x", recorder), greeting=""
        )
        await session.start(agent=agent)
        for text in messages:
            await session.run(user_input=text)
        await session.aclose()

    asyncio.run(go())
    return recorder, llm


def test_the_model_is_offered_all_twelve_tools_with_proper_descriptions():
    recorder = CallRecorder("call-x", "web", None, {})
    built = voice_tools.build_tools(KEYS["dental"], "s", recorder)
    assert len(built) == 12 and all(isinstance(t, FunctionTool) for t in built)
    by_name = {t.info.name: t for t in built}
    assert "book_appointment" in by_name and "email_my_invoice" in by_name
    assert "customer_confirmed" in str(by_name["book_appointment"].info)
    assert "Search this company's FAQ" in by_name["search_company_faq"].info.description


def test_a_question_runs_the_faq_tool_with_the_right_companys_key(api):
    def script(ctx):
        return ("text", "We are open nine to six.") if last_is_tool_output(ctx) else (
            "tool", "search_company_faq", {"question": "opening hours"})

    recorder, llm = run_call(script, ["What are your opening hours?"])
    assert [s["path"] for s in api] == ["/faq/search"] and api[0]["key"] == KEYS["dental"]
    assert recorder.tools == [{"name": "search_company_faq", "ok": True}]
    assert [l["role"] for l in recorder.lines] == ["user", "assistant"]
    assert recorder.lines[1]["text"] == "We are open nine to six."
    assert recorder.outcome() == "completed"
    assert "search_company_faq" in llm.seen_tools


def test_a_write_without_confirmation_never_reaches_the_api(api, events):
    def script(ctx):
        return ("text", "Please say yes to confirm.") if last_is_tool_output(ctx) else (
            "tool", "transfer_to_human", {"reason": "wants a person", "customer_confirmed": False})

    recorder, _ = run_call(script, ["Connect me to a person"])
    assert api == [] and events() == []
    assert recorder.tools == [{"name": "transfer_to_human", "ok": False}]
    assert recorder.outcome() == "completed"  # no handoff happened, so none is claimed


def test_a_confirmed_handoff_is_recorded_as_a_handoff(api, events, n8n):
    def script(ctx):
        return ("text", "The team has been alerted.") if last_is_tool_output(ctx) else (
            "tool", "transfer_to_human",
            {"reason": "wants a person", "customer_confirmed": True, "customer_phone": ASHA})

    recorder, _ = run_call(script, ["Yes, please connect me"])
    assert [e["type"] for e in events()] == ["escalation_created"]
    assert recorder.outcome() == "handoff"
    assert recorder.payload()["tools_used"] == [{"name": "transfer_to_human", "ok": True}]


def test_every_turn_gets_latency_numbers_when_metrics_exist(api):
    recorder = CallRecorder("call-lat", "web", None, {})
    recorder.on_message("assistant", "Hello", {})
    recorder.on_message("user", "Hours?", {"stopped_speaking_at": 10.0, "end_of_turn_delay": 0.3})
    recorder.on_message("assistant", "Let me check.", {"started_speaking_at": 11.1, "llm_node_ttft": 0.5, "tts_node_ttfb": 0.2})
    recorder.on_message("assistant", "We open at nine.", {"started_speaking_at": 14.0, "llm_node_ttft": 0.4})
    assert len(recorder.turns) == 1  # only the first answer to a question is what the caller waits for
    assert recorder.turns[0]["total_ms"] == 1100 and recorder.turns[0]["source"] == "measured"


def test_the_voice_prompt_adds_speaking_rules_to_the_normal_rules():
    prompt = build_voice_prompt({"agent_name": "Maya", "name": "Smile Dental", "timezone": "Asia/Kolkata",
                                 "instructions": "Be kind."})
    assert "Never guess" in prompt and "customer_confirmed" in prompt
    assert prompt.endswith(VOICE_RULES)


# ---------- the session event wiring ----------

class FakeSession:
    """Collects the handlers wire_events registers, so tests can fire events by hand."""

    def __init__(self):
        self.handlers, self.replies = {}, []

    def on(self, name):
        def register(fn):
            self.handlers[name] = fn
            return fn
        return register

    def generate_reply(self, **kwargs):
        self.replies.append(kwargs)

    def say(self, text):
        self.replies.append({"say": text})


class Event:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_a_session_that_closes_with_an_error_marks_the_call_failed():
    session, recorder = FakeSession(), CallRecorder("call-w", "web", None, {})
    wire_events(session, recorder, hang_up=None)
    session.handlers["close"](Event(error=None))
    assert recorder.failed is False
    session.handlers["close"](Event(error=RuntimeError("tts down")))
    assert recorder.failed is True


def test_a_silent_caller_is_asked_once_then_the_call_is_ended():
    from app.voice.worker import GOODBYE_SILENT
    session, recorder, said = FakeSession(), CallRecorder("call-w", "web", None, {}), []

    async def hang_up(message):
        said.append(message)

    async def go():
        wire_events(session, recorder, hang_up)
        away = Event(new_state="away")
        session.handlers["user_state_changed"](away)
        assert len(session.replies) == 1 and said == []      # first silence: just ask
        session.handlers["user_state_changed"](Event(new_state="speaking"))
        session.handlers["user_state_changed"](away)
        assert len(session.replies) == 2 and said == []      # the caller spoke in between: ask again
        session.handlers["user_state_changed"](away)
        await asyncio.sleep(0)
        assert said == [GOODBYE_SILENT]                       # silent twice in a row: goodbye

    asyncio.run(go())


def test_the_agent_greets_with_fixed_text_and_stays_quiet_without_one():
    class Host:
        def __init__(self):
            self.said = []

        def say(self, text):
            self.said.append(text)

    for greeting, expected in (("Hello, Smile Dental.", ["Hello, Smile Dental."]), ("", [])):
        agent = JarvisAgent("x", [], greeting)
        host = Host()
        agent.__dict__["_session"] = host
        type(agent).session = property(lambda self: self.__dict__["_session"])
        try:
            asyncio.run(agent.on_enter())
        finally:
            del type(agent).session
        assert host.said == expected


def test_a_tool_that_crashes_is_recorded_as_failed_and_the_error_is_not_swallowed(monkeypatch):
    recorder = CallRecorder("call-c", "web", None, {})

    def broken(question: str) -> dict:
        """Search."""
        raise RuntimeError("boom")

    tool = voice_tools.adapt(broken, recorder)
    with pytest.raises(RuntimeError):
        asyncio.run(tool("hours"))
    assert recorder.tools == [{"name": "broken", "ok": False}]


# ---------- when the AI model breaks down ----------

def test_an_ai_breakdown_gets_one_apology_and_the_call_is_recorded_as_failed():
    from app.voice.worker import APOLOGY
    session, recorder = FakeSession(), CallRecorder("call-e", "web", None, {})
    wire_events(session, recorder, hang_up=None)
    recorder.on_message("assistant", "Hello", {})
    recorder.on_message("user", "What are your working hours?", {})
    recoverable = Event(error=Event(recoverable=True))
    session.handlers["error"](recoverable)
    assert session.replies == []                       # one hiccup: the retry may still work
    session.handlers["error"](recoverable)
    session.handlers["error"](Event(error=Event(recoverable=False)))
    assert session.replies == [{"say": APOLOGY}]       # given up: apologise once, not three times
    assert recorder.outcome() == "failed"              # the caller's question was never answered


def test_an_error_that_was_followed_by_an_answer_is_not_a_failure():
    session, recorder = FakeSession(), CallRecorder("call-e", "web", None, {})
    wire_events(session, recorder, hang_up=None)
    recorder.on_message("user", "Hours?", {})
    session.handlers["error"](Event(error=Event(recoverable=True)))
    recorder.on_message("assistant", "We open at nine.", {})
    assert recorder.outcome() == "completed"


def test_a_failure_with_no_error_event_is_still_not_called_a_failure():
    recorder = CallRecorder("call-e", "web", None, {})
    recorder.on_message("user", "Hello?", {})  # unanswered, but nothing broke (the caller just left)
    assert recorder.outcome() == "completed"
