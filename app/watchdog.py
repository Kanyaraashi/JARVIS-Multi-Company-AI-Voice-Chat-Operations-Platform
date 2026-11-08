"""Watches JARVIS and tells you when something is wrong (Step 31).

    python -m app.watchdog              check once (run it every 5 minutes with a scheduler)
    python -m app.watchdog --loop 300   check every 300 seconds, forever

Set ALERT_WEBHOOK_URL in .env to a Slack, Discord or n8n webhook address and you get a message.
Without it, problems are only printed. You get one message when a problem appears, a reminder every
6 hours while it lasts, and one "recovered" message when it is gone. Keys and customer data are never sent.
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import CallRecord, Company, WorkflowEvent

REMIND_EVERY = timedelta(hours=6)


def collect_problems(api_ok: bool, api_note: str, db: Optional[Session], spool_waiting: int,
                     now: datetime, window_minutes: int = 30, stuck_minutes: int = 15) -> List[str]:
    problems = []
    if not api_ok:
        problems.append(f"The API is not answering ({api_note}).")
    if db is not None:
        since = now - timedelta(minutes=window_minutes)
        rows = db.execute(
            select(Company.slug, func.count()).join(CallRecord, CallRecord.company_id == Company.id)
            .where(CallRecord.outcome == "failed", CallRecord.started_at >= since).group_by(Company.slug)
        ).all()
        for slug, n in rows:
            problems.append(f"{n} call(s) broke down for {slug} in the last {window_minutes} minutes.")
        old = now - timedelta(minutes=stuck_minutes)
        rows = db.execute(
            select(Company.slug, func.count()).join(WorkflowEvent, WorkflowEvent.company_id == Company.id)
            .where(WorkflowEvent.status.in_(("failed", "pending")), WorkflowEvent.created_at <= old)
            .group_by(Company.slug)
        ).all()
        for slug, n in rows:
            problems.append(f"{n} notification(s) for {slug} are failed or stuck for over {stuck_minutes} minutes (n8n down?).")
    if spool_waiting:
        problems.append(f"{spool_waiting} call record(s) are waiting in voice_spool (the API was unreachable).")
    return problems


def decide(problems: List[str], state: dict, now: datetime):
    """Returns (message or None, new_state). Avoids spamming the same alert."""
    fingerprint = hashlib.sha256("\n".join(sorted(problems)).encode()).hexdigest() if problems else ""
    last_time = datetime.fromisoformat(state["sent_at"]) if state.get("sent_at") else None
    if not problems:
        if state.get("fingerprint"):
            return "JARVIS has recovered. No problems found.", {"fingerprint": "", "sent_at": now.isoformat()}
        return None, state
    if fingerprint != state.get("fingerprint") or last_time is None or now - last_time >= REMIND_EVERY:
        return "JARVIS needs attention:\n- " + "\n- ".join(problems), {"fingerprint": fingerprint, "sent_at": now.isoformat()}
    return None, state


def send(url: str, message: str, post: Callable = httpx.post) -> bool:
    try:
        r = post(url, json={"text": message, "content": message}, timeout=10)
        return 200 <= r.status_code < 300
    except Exception:
        return False


def run_once(env=os.environ, get: Callable = httpx.get, post: Callable = httpx.post,
             now: Optional[datetime] = None, state_file: Optional[pathlib.Path] = None) -> List[str]:
    now = now or datetime.now(timezone.utc)
    base = (env.get("JARVIS_API_BASE") or "http://localhost:8000").rstrip("/")
    try:
        r = get(base + "/health", timeout=8)
        api_ok, note = r.status_code == 200, f"HTTP {r.status_code}"
    except Exception:
        api_ok, note = False, "no connection"
    db_problem_note = None
    db = None
    url = env.get("ADMIN_DATABASE_URL") or env.get("DATABASE_URL")
    engine = create_engine(url) if url else None
    problems: List[str] = []
    try:
        if engine is not None:
            with Session(engine) as db:
                problems = collect_problems(api_ok, note, db, spool_count(env), now)
        else:
            problems = collect_problems(api_ok, note, None, spool_count(env), now)
    except Exception:
        problems = collect_problems(api_ok, note, None, spool_count(env), now) + ["The database is not answering."]
    state_file = state_file or pathlib.Path(env.get("WATCHDOG_STATE", ".watchdog_state.json"))
    try:
        state = json.loads(state_file.read_text())
    except (OSError, ValueError):
        state = {}
    message, new_state = decide(problems, state, now)
    if message:
        hook = (env.get("ALERT_WEBHOOK_URL") or "").strip()
        delivered = send(hook, message, post) if hook else False
        print(message + ("" if hook else "\n(No ALERT_WEBHOOK_URL set, so nobody was messaged.)"))
        if hook and not delivered:
            print("The alert message could not be delivered. Check ALERT_WEBHOOK_URL.")
            new_state = state          # try again next time
    try:
        state_file.write_text(json.dumps(new_state))
    except OSError:
        pass
    return problems


def spool_count(env) -> int:
    folder = env.get("VOICE_SPOOL_DIR") or "voice_spool"
    try:
        return len([f for f in os.listdir(folder) if f.endswith(".json")])
    except FileNotFoundError:
        return 0


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--loop", type=int, default=0, help="seconds between checks (0 = once)")
    args = parser.parse_args(argv)
    while True:
        problems = run_once()
        if not args.loop:
            print("OK, nothing wrong." if not problems else f"{len(problems)} problem(s) found.")
            return 1 if problems else 0
        time.sleep(max(30, args.loop))


if __name__ == "__main__":
    sys.exit(main())
