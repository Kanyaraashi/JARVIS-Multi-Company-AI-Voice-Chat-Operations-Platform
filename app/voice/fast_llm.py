"""A faster and quieter way to switch between AI models during a call (Step 25).

What the caller experiences:
  - If the first model has not produced anything within `first_token_seconds` (default 6),
    the next model takes over. The caller is never told that a model was switched.
  - If nothing has been said after `filler_after_seconds` (default 2.5), the caller hears
    "One moment please." once per question, so a slow answer never feels like silence.
  - After a switch, the working model keeps the conversation until the end of the question.
    (Gemini 3 hides small notes inside each tool call that only the model that made the call
    can hand back, so a question must not jump between models half way.)
  - A model that failed rests for `cooldown_seconds`, then the first model is tried again at
    the start of a new question.

Why not LiveKit's own FallbackAdapter: its time limit is also sent to Gemini as the request
deadline, and Gemini refuses deadlines under 10 seconds. Here the 6 second limit is ours:
the request itself still gets a 12 second deadline.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from livekit.agents import APIConnectionError, APIConnectOptions, llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN

log = logging.getLogger("jarvis.voice.llm")


class TooSlow(Exception):
    """The model produced nothing within the allowed time."""


@dataclass
class Hooks:
    """Optional callbacks, so the call record can learn what happened."""

    on_first_token: Optional[Callable[[int], None]] = None  # milliseconds the model really took
    on_filler: Optional[Callable[[], None]] = None
    on_switch: Optional[Callable[[str, str, str], None]] = None  # from model, to model, reason


def turn_marker(chat_ctx: llm.ChatContext) -> Optional[str]:
    """Identifies the caller's current question (their latest message)."""
    for item in reversed(chat_ctx.items):
        if item.type == "message" and item.role == "user":
            return item.id
    return None


class FastFailoverLLM(llm.LLM):
    def __init__(
        self,
        models: list,
        *,
        first_token_seconds: float = 6.0,
        filler_after_seconds: float = 2.5,
        filler_text: str = "One moment please.",
        attempt_timeout: float = 12.0,
        cooldown_seconds: float = 60.0,
        hooks: Optional[Hooks] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        if not models:
            raise ValueError("at least one model is needed")
        self._models = list(models)
        self.first_token_seconds = first_token_seconds
        self.filler_after_seconds = filler_after_seconds
        self.filler_text = filler_text
        self._attempt_timeout = attempt_timeout
        self.cooldown_seconds = cooldown_seconds
        self.hooks = hooks or Hooks()
        self._clock = clock
        self._active = 0
        self._resting_until: dict = {}
        self._filled_for: Optional[str] = None

    @property
    def model(self) -> str:
        return self._models[self._active].model

    @property
    def provider(self) -> str:
        return self._models[self._active].provider

    def prewarm(self, *, loop=None) -> None:
        self._models[0].prewarm(loop=loop)

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: Optional[list] = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls=NOT_GIVEN,
        tool_choice=NOT_GIVEN,
        extra_kwargs=NOT_GIVEN,
    ) -> "FastStream":
        return FastStream(
            self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options,
            parallel_tool_calls=parallel_tool_calls, tool_choice=tool_choice, extra_kwargs=extra_kwargs,
        )

    # --- which model goes first -----------------------------------------------------
    def order_for(self, chat_ctx: llm.ChatContext) -> list:
        now = self._clock()
        items = chat_ctx.items
        same_question = bool(items) and items[-1].type == "function_call_output"
        count = len(self._models)
        if not same_question:  # a fresh question: go back to the best model that is not resting
            self._active = next((i for i in range(count) if self._resting_until.get(i, 0) <= now), 0)
        order = [self._active] + [i for i in range(count) if i != self._active]
        ready = [i for i in order if self._resting_until.get(i, 0) <= now]
        return ready + [i for i in order if i not in ready]

    def rest(self, index: int) -> None:
        self._resting_until[index] = self._clock() + self.cooldown_seconds


class FastStream(llm.LLMStream):
    _llm_attempt_span_name = None
    _genai_operation_name = None

    def __init__(self, wrapper: FastFailoverLLM, *, chat_ctx, tools, conn_options,
                 parallel_tool_calls, tool_choice, extra_kwargs) -> None:
        super().__init__(wrapper, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._wrapper = wrapper
        self._parallel = parallel_tool_calls
        self._tool_choice = tool_choice
        self._extra = extra_kwargs
        self._heard_real_output = False

    async def _run(self) -> None:
        wrapper = self._wrapper
        order = wrapper.order_for(self._chat_ctx)
        marker = turn_marker(self._chat_ctx)
        began = wrapper._clock()
        last_error: Optional[BaseException] = None
        previous = None

        for index in order:
            model = wrapper._models[index]
            if previous is not None and wrapper.hooks.on_switch:
                wrapper.hooks.on_switch(previous[0], model.model, previous[1])
            try:
                await self._serve(index, model, marker, began)
                wrapper._active = index
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                wrapper.rest(index)
                reason = "too slow" if isinstance(exc, TooSlow) else type(exc).__name__
                log.warning("model %s failed (%s: %s)", model.model, reason, str(exc)[:200])
                if self._heard_real_output:
                    # the caller already heard words; starting over would repeat them,
                    # so end the answer here and tell LiveKit not to retry it.
                    raise APIConnectionError(
                        f"model {model.model} stopped after the caller heard part of the answer",
                        retryable=False,
                    ) from exc
                last_error, previous = exc, (model.model, reason)

        raise APIConnectionError(
            f"all {len(order)} voice models failed or were too slow", retryable=False
        ) from last_error

    async def _serve(self, index: int, model, marker: Optional[str], began: float) -> None:
        wrapper = self._wrapper
        clock = wrapper._clock
        stream = model.chat(
            chat_ctx=self._chat_ctx, tools=self._tools,
            conn_options=APIConnectOptions(max_retry=0, timeout=wrapper._attempt_timeout),
            parallel_tool_calls=self._parallel, tool_choice=self._tool_choice,
            extra_kwargs=self._extra,
        )
        iterator = stream.__aiter__()
        started = clock()
        pending: Optional[asyncio.Future] = None
        got_real = False
        want_filler = marker is not None and wrapper._filled_for != marker
        try:
            while True:
                if pending is None:
                    pending = asyncio.ensure_future(iterator.__anext__())
                timeout = None
                if not got_real:
                    timeout = max(0.0, wrapper.first_token_seconds - (clock() - started))
                    if want_filler:
                        timeout = min(timeout, max(0.0, wrapper.filler_after_seconds - (clock() - began)))
                done, _ = await asyncio.wait({pending}, timeout=timeout)

                if not done:
                    if want_filler and clock() - began >= wrapper.filler_after_seconds:
                        want_filler = False
                        wrapper._filled_for = marker
                        self._event_ch.send_nowait(llm.ChatChunk(
                            id="filler",
                            delta=llm.ChoiceDelta(role="assistant", content=wrapper.filler_text + " "),
                        ))
                        if wrapper.hooks.on_filler:
                            wrapper.hooks.on_filler()
                        continue
                    if clock() - started >= wrapper.first_token_seconds:
                        raise TooSlow(f"nothing after {wrapper.first_token_seconds:g} seconds")
                    continue

                task, pending = pending, None
                try:
                    chunk = task.result()
                except StopAsyncIteration:
                    if not got_real:
                        raise APIConnectionError("the model returned nothing", retryable=True)
                    return
                if not got_real and chunk.has_response():
                    got_real = True
                    self._heard_real_output = True
                    if wrapper.hooks.on_first_token:
                        wrapper.hooks.on_first_token(int((clock() - began) * 1000))
                if chunk.delta and chunk.delta.content:
                    wrapper._filled_for = marker  # the model spoke by itself: no filler needed
                self._event_ch.send_nowait(chunk)
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
            try:
                await stream.aclose()
            except Exception:
                pass
