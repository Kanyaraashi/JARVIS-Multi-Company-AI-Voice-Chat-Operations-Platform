"""Collects what happens during one call and saves it when the call ends (Step 24)."""
import json
import os
import pathlib
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.latency import turn_latency
from app.privacy import redact

MAX_LINES, MAX_TOOLS, MAX_TURNS, MAX_TEXT = 400, 100, 400, 2000


class CallRecorder:
    def __init__(self, room_name: str, direction: str, caller_phone: Optional[str], providers: dict, clock=time.time):
        self.room_name = room_name
        self.direction = direction
        self.caller_phone = caller_phone
        self.providers = providers
        self.clock = clock
        self.started = clock()
        self.lines = []
        self.tools = []
        self.turns = []
        self.failed = False
        self.errors = 0
        self._waiting_user_metrics = None

    # --- things the voice session tells us -------------------------------------------
    def on_message(self, role: str, text: Optional[str], metrics: Optional[dict]) -> None:
        text = (text or "").strip()
        if role not in ("user", "assistant") or not text:
            return
        self.lines.append({"role": role, "text": redact(text)[:MAX_TEXT]})
        if role == "user":
            self._waiting_user_metrics = metrics or {}
        elif self._waiting_user_metrics is not None:
            # Only the FIRST answer after a question counts: that is what the caller waits for.
            measured = turn_latency(self._waiting_user_metrics, metrics or {})
            self._waiting_user_metrics = None
            if measured:
                self.turns.append(measured)

    def tool_finished(self, name: str, result) -> None:
        ok = isinstance(result, dict) and result.get("ok") is True
        self.tools.append({"name": name, "ok": ok})

    def mark_failed(self) -> None:
        self.failed = True

    def on_error(self) -> None:
        self.errors += 1

    def unanswered(self) -> bool:
        """The caller said something and the agent never answered it."""
        return self._waiting_user_metrics is not None

    # --- the record --------------------------------------------------------------------
    def outcome(self) -> str:
        if any(t["name"] == "transfer_to_human" and t["ok"] for t in self.tools):
            return "handoff"
        # A call where the AI broke down and the caller's last words got no answer is a
        # failure, even if the caller hung up first. It must never look like a success.
        if self.failed or (self.errors > 0 and self.unanswered()):
            return "failed"
        if not any(line["role"] == "user" for line in self.lines):
            return "abandoned"
        return "completed"

    def last_user_text(self) -> str:
        for line in reversed(self.lines):
            if line["role"] == "user":
                return line["text"]
        return ""

    def payload(self) -> dict:
        def iso(seconds: float) -> str:
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat()

        return {
            "room_name": self.room_name,
            "direction": self.direction,
            "caller_phone": self.caller_phone,
            "started_at": iso(self.started),
            "ended_at": iso(max(self.clock(), self.started)),
            "outcome": self.outcome(),
            "transcript": self.lines[:MAX_LINES],
            "tools_used": self.tools[:MAX_TOOLS],
            "latency_turns": self.turns[:MAX_TURNS],
            "providers": self.providers,
        }


# ---------- saving, with a safety net ------------------------------------------------------

def spool_dir() -> pathlib.Path:
    return pathlib.Path(os.getenv("VOICE_SPOOL_DIR", "voice_spool"))


def spool(company_slug: str, payload: dict, reason: str) -> pathlib.Path:
    """If the API cannot be reached, the record is kept on disk instead of being lost.
    The file never contains an API key. Send it later with: python -m app.voice.spool"""
    folder = spool_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{company_slug}__{payload['room_name']}.json"
    path.write_text(json.dumps({"company": company_slug, "payload": payload, "reason": reason}, indent=1))
    return path


def send(api_base: str, api_key: str, payload: dict, attempts: int = 3, pause: float = 1.0):
    """Returns (saved, reason). Retrying is safe: the API saves each room only once."""
    reason = "not tried"
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.post(api_base + "/calls", json=payload, headers={"X-API-Key": api_key}, timeout=15)
        except httpx.RequestError as exc:
            reason = f"API not reachable ({type(exc).__name__})"
        else:
            if response.status_code == 200:
                return True, "saved"
            reason = f"API answered {response.status_code}: {response.text[:200]}"
            if response.status_code < 500 and response.status_code != 429:
                break  # sending it again cannot fix a rejected record
        if attempt < attempts:
            time.sleep(pause * attempt)
    return False, reason
