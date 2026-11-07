"""Tests the AI brain of the voice agent WITHOUT any audio.

    python -m app.voice.text_check "What are your opening hours?"
    python -m app.voice.text_check "What are your opening hours?" shopeasy

It runs the same Gemini model, instructions and tools the phone agent uses, but with
typed text. If this works and a real call does not, the problem is in the audio (microphone,
Deepgram or Sarvam). If this fails, it prints the exact error from Gemini or the tools.
"""
import asyncio
import sys
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

from livekit.agents import AgentSession  # noqa: E402

from app.agent_tools import API_BASE  # noqa: E402
from app.privacy import install_log_redaction  # noqa: E402
from app.voice import config, providers  # noqa: E402
from app.voice.prompt import build_voice_prompt  # noqa: E402
from app.voice.recorder import CallRecorder  # noqa: E402
from app.voice.tools import build_tools  # noqa: E402
from app.voice.worker import JarvisAgent  # noqa: E402

install_log_redaction()


def describe_error(error) -> str:
    inner = getattr(error, "error", None) or error
    parts = [type(inner).__name__, str(inner)[:500]]
    for name in ("status_code", "body"):
        value = getattr(inner, name, None)
        if value:
            parts.append(f"{name}={str(value)[:400]}")
    return " | ".join(parts)


async def run_check(llm, company: dict, api_key: str, question: str, timeout: float = 90) -> dict:
    recorder = CallRecorder("text-check", "web", None, {})
    errors = []
    session = AgentSession(llm=llm)

    @session.on("conversation_item_added")
    def _item(event):
        item = event.item
        if getattr(item, "type", None) == "message":
            recorder.on_message(item.role, item.text_content, dict(item.metrics or {}))

    @session.on("error")
    def _error(event):
        errors.append(describe_error(getattr(event, "error", event)))

    agent = JarvisAgent(
        build_voice_prompt(company), build_tools(api_key, uuid.uuid4().hex, recorder), greeting=""
    )
    await session.start(agent=agent)
    try:
        await asyncio.wait_for(session.run(user_input=question), timeout)
    except Exception as exc:  # timeout or the model giving up
        errors.append(describe_error(exc))
    await session.aclose()
    answers = [line["text"] for line in recorder.lines if line["role"] == "assistant"]
    return {"answers": answers, "tools": recorder.tools, "errors": errors}


async def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else "What are your opening hours?"
    slug = sys.argv[2] if len(sys.argv) > 2 else "smile-dental"
    key = config.company_key(slug)
    if not key:
        sys.exit(f"No key for {slug} in .env")
    company = httpx.get(API_BASE + "/company/me", headers={"X-API-Key": key}, timeout=10).json()
    print(f"Company: {company['name']}   Question: {question}\n")
    result = await run_check(providers.build_llm(), company, key, question)
    print("Tools used :", result["tools"] or "none")
    print("Answer     :", " ".join(result["answers"]) or "(no answer)")
    if result["errors"]:
        print("\nERRORS (first one matters most):")
        for number, text in enumerate(result["errors"], 1):
            print(f" {number}. {text}")
    else:
        print("\nNo errors. The AI part works.")


if __name__ == "__main__":
    asyncio.run(main())
