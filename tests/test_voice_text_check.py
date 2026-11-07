"""The no-audio check that tells a broken AI apart from a broken microphone."""
import asyncio

from app import agent_tools
from app.voice.text_check import describe_error, run_check
from conftest import KEYS
from test_voice_session import ScriptedLLM, api, last_is_tool_output  # noqa: F401


def company():
    return {"agent_name": "Maya", "name": "Smile Dental", "timezone": "Asia/Kolkata", "instructions": "Be kind."}


def test_the_check_shows_the_tool_and_the_answer(api):
    def script(ctx):
        return ("text", "We are open nine to six.") if last_is_tool_output(ctx) else (
            "tool", "search_company_faq", {"question": "opening hours"})

    result = asyncio.run(run_check(ScriptedLLM(script), company(), KEYS["dental"], "What are your opening hours?"))
    assert result["tools"] == [{"name": "search_company_faq", "ok": True}]
    assert result["answers"] == ["We are open nine to six."] and result["errors"] == []


def test_errors_are_described_with_status_and_body():
    class Boom(Exception):
        status_code = 404
        body = {"error": {"message": "models/x is not found"}}

    text = describe_error(Boom("gemini llm: client error"))
    assert "Boom" in text and "404" in text and "not found" in text
