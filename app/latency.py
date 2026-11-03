"""Measures how long the caller waits for an answer (Step 25).

The delay the caller feels is: from the moment they stop talking until the agent
starts talking. It is made of three parts:
  listen = deciding the caller has finished (speech-to-text and turn detection)
  think  = the AI model producing its first words (includes any tools it ran first)
  speak  = the voice service producing its first sound
"""
import math
from typing import Optional

MAX_PLAUSIBLE_SECONDS = 60


def _ms(seconds) -> Optional[int]:
    if seconds is None:
        return None
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    if value < 0 or math.isnan(value) or math.isinf(value):
        return None
    return int(round(value * 1000))


def turn_latency(user: dict, assistant: dict) -> Optional[dict]:
    """Latency of one question and answer. `user` and `assistant` are the metrics
    LiveKit attaches to the two chat messages. Returns None if nothing was measured."""
    listen = _ms(user.get("end_of_turn_delay"))
    if listen is None:
        listen = _ms(user.get("transcription_delay"))
    think = _ms(assistant.get("llm_node_ttft"))
    speak = _ms(assistant.get("tts_node_ttfb"))

    total, source = None, "estimated"
    stopped = user.get("stopped_speaking_at")
    started = assistant.get("started_speaking_at")
    if stopped is not None and started is not None:
        gap = started - stopped
        if 0 <= gap <= MAX_PLAUSIBLE_SECONDS:
            total, source = _ms(gap), "measured"
    if total is None:
        parts = [p for p in (listen, think, speak) if p is not None]
        if not parts:
            return None
        total = sum(parts)

    return {
        "total_ms": total,
        "listen_ms": listen,
        "think_ms": think,
        "speak_ms": speak,
        "source": source,
    }


def percentile(values: list, pct: float) -> Optional[int]:
    """Nearest-rank percentile: the value that `pct` percent of answers were at or under."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(turns: list, target_ms: int = 1500) -> dict:
    totals = [t["total_ms"] for t in turns if t.get("total_ms") is not None]
    if not totals:
        return {
            "turns": 0, "avg_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None,
            "target_ms": target_ms, "within_target_pct": None,
            "average_by_part": {"listen_ms": None, "think_ms": None, "speak_ms": None},
        }
    by_part = {}
    for part in ("listen_ms", "think_ms", "speak_ms"):
        values = [t[part] for t in turns if t.get(part) is not None]
        by_part[part] = round(sum(values) / len(values)) if values else None
    return {
        "turns": len(totals),
        "avg_ms": round(sum(totals) / len(totals)),
        "p50_ms": percentile(totals, 50),
        "p95_ms": percentile(totals, 95),
        "max_ms": max(totals),
        "target_ms": target_ms,
        "within_target_pct": round(100 * sum(1 for x in totals if x <= target_ms) / len(totals)),
        "average_by_part": by_part,
    }
