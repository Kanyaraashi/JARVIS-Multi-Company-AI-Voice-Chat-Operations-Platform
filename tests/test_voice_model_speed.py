import asyncio

from livekit.agents import llm

from app.voice import model_speed
from test_voice_fast_llm import FakeModel, text


def test_it_measures_the_time_until_the_first_response():
    ctx = llm.ChatContext()
    ctx.add_message(role="user", content="hi")
    seconds = asyncio.run(model_speed.first_response_seconds(FakeModel("A", [(0.2, text("hello"))]), ctx, [], 5))
    assert 0.15 <= seconds <= 0.6


def test_a_failing_model_gives_none_not_a_crash():
    from livekit.agents import APIConnectionError
    ctx = llm.ChatContext()
    ctx.add_message(role="user", content="hi")
    model = FakeModel("A", [(0.01, APIConnectionError("503"))])
    assert asyncio.run(model_speed.first_response_seconds(model, ctx, [], 5)) is None


def test_the_advice_names_the_fastest_and_a_backup():
    advice = model_speed.verdict({"slow": [5.0, 6.0], "fast": [0.8, 0.9], "mid": [1.5, None]})
    assert "Fastest: fast" in advice and "GEMINI_FALLBACK_MODELS" in advice and "mid" in advice
    assert "slow" in advice.split("poor choice")[1]
    assert "No model answered" in model_speed.verdict({"a": [None]})
