"""Step 25: a whole call where the first AI model hangs. The caller must still get the
right answer, hear "One moment please." once, and never hear that a model was switched."""
import asyncio
import json

from livekit.agents import AgentSession
from livekit.agents.llm import ChatChunk, ChoiceDelta, FunctionToolCall, LLM, LLMStream
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

from app.latency import summarize
from app.voice import tools as voice_tools
from app.voice.fast_llm import FastFailoverLLM, Hooks
from app.voice.recorder import CallRecorder
from app.voice.worker import JarvisAgent, bind_hooks, wire_events
from conftest import KEYS
from test_voice_session import api, last_is_tool_output  # noqa: F401  (the api fixture)


class DelayedStream(LLMStream):
    async def _run(self) -> None:
        await asyncio.sleep(self._llm.delay)
        if self._llm.broken:
            from livekit.agents import APIConnectionError
            raise APIConnectionError("503 high demand")
        if last_is_tool_output(self._chat_ctx):
            delta = ChoiceDelta(role="assistant", content="We are open nine to six.")
        else:
            call = FunctionToolCall(name="search_company_faq", arguments=json.dumps({"question": "hours"}),
                                    call_id=f"call_{len(self._chat_ctx.items)}")
            delta = ChoiceDelta(role="assistant", tool_calls=[call])
        self._event_ch.send_nowait(ChatChunk(id="x", delta=delta))


class DelayedLLM(LLM):
    def __init__(self, name, delay, broken=False):
        super().__init__()
        self.name, self.delay, self.broken, self.calls = name, delay, broken, 0

    @property
    def model(self):
        return self.name

    def chat(self, *, chat_ctx, tools=None, conn_options=None, **kwargs):
        self.calls += 1
        return DelayedStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options or DEFAULT_API_CONNECT_OPTIONS)


def play(models, question="What are your opening hours?"):
    recorder = CallRecorder("call-failover", "inbound", "+919000000001", {})
    hooks = Hooks()
    chain = FastFailoverLLM(models, first_token_seconds=0.4, filler_after_seconds=0.15, hooks=hooks)
    bind_hooks(hooks, recorder)

    async def go():
        session = AgentSession(llm=chain)
        wire_events(session, recorder, hang_up=lambda message: asyncio.sleep(0))
        agent = JarvisAgent("You are a test agent.", voice_tools.build_tools(KEYS["dental"], "s", recorder), greeting="")
        await session.start(agent=agent)
        await session.run(user_input=question)
        await session.aclose()

    asyncio.run(go())
    return recorder


def caller_heard(recorder):
    return " ".join(l["text"] for l in recorder.lines if l["role"] == "assistant")


def test_a_hanging_first_model_is_replaced_and_the_caller_only_hears_one_moment(api):
    hung, good = DelayedLLM("model-A", delay=30), DelayedLLM("model-B", delay=0.02)
    recorder = play([hung, good])
    heard = caller_heard(recorder)
    assert "One moment please." in heard and heard.count("One moment") == 1
    assert "We are open nine to six." in heard
    assert "model" not in heard.lower()
    assert [s["key"] for s in api] == [KEYS["dental"]]            # the tool still ran with the right key
    assert recorder.outcome() == "completed" and recorder.switches == 1
    assert recorder.turns and recorder.turns[0]["switched"] is True and recorder.turns[0]["filler"] is True


def test_a_broken_first_model_is_replaced_instantly_with_no_filler(api):
    broken, good = DelayedLLM("model-A", delay=0.01, broken=True), DelayedLLM("model-B", delay=0.02)
    recorder = play([broken, good])
    heard = caller_heard(recorder)
    assert "One moment" not in heard and "We are open nine to six." in heard
    assert recorder.outcome() == "completed" and recorder.switches == 1


def test_a_healthy_fast_model_is_left_alone(api):
    fast, spare = DelayedLLM("model-A", delay=0.02), DelayedLLM("model-B", delay=0.02)
    recorder = play([fast, spare])
    assert spare.calls == 0 and recorder.switches == 0
    assert "One moment" not in caller_heard(recorder)


def test_when_every_model_is_down_the_call_is_marked_failed_not_completed(api):
    recorder = play([DelayedLLM("A", 0.01, broken=True), DelayedLLM("B", 0.01, broken=True)])
    assert recorder.errors >= 1 and recorder.outcome() == "failed"


def test_the_report_shows_the_models_real_time_even_when_the_filler_hides_it():
    turns = [
        {"total_ms": 2600, "llm_real_ms": 9000, "filler": True, "switched": True},
        {"total_ms": 900, "llm_real_ms": 700},
    ]
    report = summarize(turns, target_ms=1500)
    assert report["avg_ms"] == 1750 and report["avg_llm_real_ms"] == 4850
    assert report["filler_pct"] == 50 and report["switched_pct"] == 50
    assert summarize([])["filler_pct"] is None
