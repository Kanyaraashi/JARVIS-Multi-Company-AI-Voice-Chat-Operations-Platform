"""Step 25: quiet, quick failover between AI models, and the 'one moment' filler."""
import asyncio

import pytest
from livekit.agents import APIConnectionError, llm
from livekit.agents.llm import ChatChunk, ChoiceDelta, FunctionToolCall
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

from app.voice.fast_llm import FastFailoverLLM, Hooks


class FakeStream(llm.LLMStream):
    async def _run(self) -> None:
        for delay, item in self._llm.script:
            await asyncio.sleep(delay)
            if isinstance(item, Exception):
                raise item
            self._event_ch.send_nowait(item)


class FakeModel(llm.LLM):
    def __init__(self, name, script):
        super().__init__()
        self.name, self.script, self.calls = name, script, 0

    @property
    def model(self):
        return self.name

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **kw):
        self.calls += 1
        return FakeStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


def text(words):
    return ChatChunk(id="t", delta=ChoiceDelta(role="assistant", content=words))


def tool_call(name="search_company_faq"):
    return ChatChunk(id="c", delta=ChoiceDelta(role="assistant", tool_calls=[
        FunctionToolCall(name=name, arguments="{}", call_id="call_1")]))


def question(words="What are your hours?"):
    ctx = llm.ChatContext()
    ctx.add_message(role="user", content=words)
    return ctx


def after_tool(ctx):
    """The same question, continued after a tool ran."""
    ctx = ctx.copy()
    ctx.items.append(llm.FunctionCall(call_id="call_1", name="x", arguments="{}"))
    ctx.items.append(llm.FunctionCallOutput(call_id="call_1", name="x", output="{}", is_error=False))
    return ctx


def make(models, **kw):
    options = dict(first_token_seconds=0.4, filler_after_seconds=0.15, attempt_timeout=12,
                   filler_text="One moment please.", cooldown_seconds=60)
    options.update(kw)
    return FastFailoverLLM(models, **options)


async def collect(wrapper, ctx):
    spoken, calls = [], []
    async with wrapper.chat(chat_ctx=ctx) as stream:
        async for chunk in stream:
            if chunk.delta:
                if chunk.delta.content:
                    spoken.append(chunk.delta.content)
                calls += [c.name for c in chunk.delta.tool_calls]
    return "".join(spoken), calls


def run(coro):
    return asyncio.run(coro)


def test_a_fast_model_answers_with_no_filler_and_no_switch():
    primary = FakeModel("A", [(0.01, text("We open at nine."))])
    backup = FakeModel("B", [(0.01, text("never used"))])
    said, _ = run(collect(make([primary, backup]), question()))
    assert said == "We open at nine." and backup.calls == 0


def test_a_slow_model_gets_one_moment_please_then_its_real_answer():
    primary = FakeModel("A", [(0.25, text("We open at nine."))])
    notes = []
    wrapper = make([primary], hooks=Hooks(on_filler=lambda: notes.append("filler")))
    said, _ = run(collect(wrapper, question()))
    assert said == "One moment please. We open at nine." and notes == ["filler"]


def test_a_model_that_never_answers_is_replaced_quietly_by_the_backup():
    primary = FakeModel("A", [(5, text("too late"))])
    backup = FakeModel("B", [(0.01, text("We open at nine."))])
    switches = []
    wrapper = make([primary, backup], hooks=Hooks(on_switch=lambda a, b, why: switches.append((a, b, why))))
    said, _ = run(collect(wrapper, question()))
    assert said == "One moment please. We open at nine."      # the caller hears no model names
    assert "A" not in said and "B" not in said
    assert switches == [("A", "B", "too slow")]


def test_a_model_that_errors_is_replaced_at_once_without_a_filler():
    primary = FakeModel("A", [(0.01, APIConnectionError("503 high demand"))])
    backup = FakeModel("B", [(0.01, text("We open at nine."))])
    said, _ = run(collect(make([primary, backup]), question()))
    assert said == "We open at nine."


def test_the_filler_is_said_once_per_question_even_after_a_tool_call():
    first = FakeModel("A", [(0.25, tool_call())])
    wrapper = make([first])
    ctx = question()
    said1, calls = run(collect(wrapper, ctx))
    assert said1 == "One moment please. " and calls == ["search_company_faq"]
    # the answer after the tool is also slow, but the caller was already told once
    first.script = [(0.25, text("We open at nine."))]
    said2, _ = run(collect(wrapper, after_tool(ctx)))
    assert said2 == "We open at nine."
    # a NEW question gets a new filler
    first.script = [(0.25, text("Sure."))]
    said3, _ = run(collect(wrapper, question("Another question?")))
    assert said3.startswith("One moment please.")


def test_if_the_model_speaks_by_itself_no_filler_is_added_later():
    model = FakeModel("A", [(0.01, text("Let me check. ")), (0.3, tool_call())])
    wrapper = make([model])
    ctx = question()
    said, calls = run(collect(wrapper, ctx))
    assert said == "Let me check. " and calls == ["search_company_faq"]
    model.script = [(0.3, text("We open at nine."))]
    said, _ = run(collect(wrapper, after_tool(ctx)))
    assert said == "We open at nine."   # no 'one moment' on top of 'let me check'


def test_after_a_switch_the_same_question_stays_on_the_working_model():
    primary = FakeModel("A", [(0.01, APIConnectionError("down"))])
    backup = FakeModel("B", [(0.01, tool_call())])
    wrapper = make([primary, backup])
    ctx = question()
    run(collect(wrapper, ctx))
    primary.script = [(0.01, text("A would answer"))]  # the first model has recovered...
    backup.script = [(0.01, text("We open at nine."))]
    said, _ = run(collect(wrapper, after_tool(ctx)))
    assert said == "We open at nine." and primary.calls == 1   # ...but is not used mid-question


def test_the_first_model_is_tried_again_for_a_new_question_after_its_rest():
    now = {"t": 1000.0}
    primary = FakeModel("A", [(0.01, APIConnectionError("down"))])
    backup = FakeModel("B", [(0.01, text("from B"))])
    wrapper = make([primary, backup], clock=lambda: now["t"])
    run(collect(wrapper, question()))
    primary.script = [(0.01, text("from A"))]
    said, _ = run(collect(wrapper, question("Next?")))        # A is still resting
    assert said == "from B" and primary.calls == 1
    now["t"] += 61                                             # the rest is over
    said, _ = run(collect(wrapper, question("And next?")))
    assert said == "from A"


def test_when_every_model_fails_the_error_is_final_not_retried_for_a_minute():
    models = [FakeModel("A", [(0.01, APIConnectionError("down"))]), FakeModel("B", [(5, text("late"))])]
    with pytest.raises(APIConnectionError) as caught:
        run(collect(make(models), question()))
    assert caught.value.retryable is False


def test_a_failure_after_words_were_spoken_is_not_restarted():
    primary = FakeModel("A", [(0.01, text("We open ")), (0.01, APIConnectionError("cut off"))])
    backup = FakeModel("B", [(0.01, text("never repeated"))])
    with pytest.raises(APIConnectionError):
        run(collect(make([primary, backup]), question()))
    assert backup.calls == 0


def test_the_real_model_time_is_reported_even_when_a_filler_covers_it():
    seen = []
    model = FakeModel("A", [(0.3, text("We open at nine."))])
    run(collect(make([model], hooks=Hooks(on_first_token=seen.append)), question()))
    assert len(seen) == 1 and 250 <= seen[0] <= 700


def test_a_model_that_returns_nothing_counts_as_a_failure():
    empty = FakeModel("A", [])
    backup = FakeModel("B", [(0.01, text("hello"))])
    said, _ = run(collect(make([empty, backup]), question()))
    assert said == "hello"
