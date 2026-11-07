"""Measures how fast each AI model starts answering, so you can pick a fast backup (Step 25).

Run:   python -m app.voice.model_speed                      (models from .env)
       python -m app.voice.model_speed gemini-3.1-flash-lite gemini-3.5-flash-lite
       python -m app.voice.model_speed --company smile-dental --rounds 5

It asks each model the same real question with the real prompt and the real tools, and
prints the time until the model's first response (a spoken word or a tool request).
Only that first response matters on a phone call: the caller waits for it.
"""
import argparse
import asyncio
import os
import statistics
import time
from typing import Optional

import httpx
from dotenv import load_dotenv
from livekit.agents import llm as lk_llm

from app.voice import config, providers
from app.voice.prompt import build_voice_prompt
from app.voice.recorder import CallRecorder
from app.voice.tools import build_tools

API_BASE = os.getenv("JARVIS_API_BASE", "http://localhost:8000")
QUESTION = "What are your opening hours?"


def verdict(results: dict) -> str:
    """results: model -> list of seconds (None = failed). Plain advice for the beginner."""
    ranked = []
    for name, times in results.items():
        good = [t for t in times if t is not None]
        if good:
            ranked.append((statistics.median(good), name, len(good), len(times)))
    if not ranked:
        return "No model answered. Check GEMINI_API_KEY and the model names."
    ranked.sort()
    best = ranked[0]
    lines = [f"Fastest: {best[1]} (median {best[0]:.1f}s)."]
    if len(ranked) > 1:
        lines.append(f"Use it as GEMINI_MODEL and put {ranked[1][1]} in GEMINI_FALLBACK_MODELS.")
    slow = [name for med, name, _, _ in ranked if med > 4]
    if slow:
        lines.append("Slower than 4 seconds, a poor choice for phone calls: " + ", ".join(slow))
    return " ".join(lines)


async def first_response_seconds(model, chat_ctx, tools, timeout: float) -> Optional[float]:
    started = time.monotonic()
    try:
        stream = model.chat(chat_ctx=chat_ctx, tools=tools)
        async with stream:
            async for chunk in stream:
                if chunk.has_response():
                    return time.monotonic() - started
                if time.monotonic() - started > timeout:
                    return None
    except Exception as exc:
        print(f"    failed: {type(exc).__name__}: {str(exc)[:160]}")
    return None


async def measure(names, company, api_key, rounds, timeout=30.0) -> dict:
    key = os.environ["GEMINI_API_KEY"]
    tools = build_tools(api_key, "model-speed", CallRecorder("speed", "web", None, {}))
    ctx = lk_llm.ChatContext()
    ctx.add_message(role="system", content=build_voice_prompt(company))
    ctx.add_message(role="user", content=QUESTION)
    results = {}
    for name in names:
        model = providers.build_gemini(name, key)
        print(f"\n{name}")
        results[name] = []
        for number in range(1, rounds + 1):
            seconds = await first_response_seconds(model, ctx, tools, timeout)
            results[name].append(seconds)
            print(f"  try {number}: " + (f"{seconds:.2f}s" if seconds is not None else "no answer"))
        good = [t for t in results[name] if t is not None]
        if good:
            print(f"  min {min(good):.2f}s   median {statistics.median(good):.2f}s   max {max(good):.2f}s")
    return results


async def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="*")
    parser.add_argument("--company", default=os.getenv("VOICE_DEFAULT_COMPANY", ""))
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY is missing in .env")
    names = args.models or [os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()] + [
        n.strip() for n in os.getenv("GEMINI_FALLBACK_MODELS", "").split(",") if n.strip()
    ]
    names = list(dict.fromkeys(names))
    if any("latest" in n for n in names):
        raise SystemExit("Use exact model names, not '-latest' aliases.")
    slug = args.company
    api_key = config.company_key(slug) if slug else None
    if not api_key:
        raise SystemExit("Give a company: --company smile-dental (its JARVIS_KEY_... must be in .env)")
    company = httpx.get(API_BASE + "/company/me", headers={"X-API-Key": api_key}, timeout=10).json()
    print(f"Company: {company['name']}   Question: {QUESTION}   Rounds: {args.rounds}")
    results = await measure(names, company, api_key, max(1, args.rounds))
    print("\n" + verdict(results))


if __name__ == "__main__":
    asyncio.run(main())
