import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import func, select

from app.audit import client_ip
from app.db import SessionLocal
from app.events import send_event
from app.models import WorkflowEvent
from app.ratelimit import failure_limiter, reject

router = APIRouter(prefix="/internal")

MAX_ATTEMPTS = 5
MIN_AGE_MINUTES = 1


def check_secret(provided: Optional[str], request: Request) -> None:
    ip = client_ip(request)
    wait = failure_limiter.retry_after(ip)
    if wait:
        reject(wait)
    secret = os.getenv("N8N_WEBHOOK_SECRET")
    if not secret or not provided or not hmac.compare_digest(provided, secret):
        failure_limiter.hit(ip)
        raise HTTPException(status_code=401, detail="Invalid secret")


def count(db, *conditions) -> int:
    return (
        db.scalar(select(func.count()).select_from(WorkflowEvent).where(*conditions)) or 0
    )


@router.post("/retry-events")
def retry_events(request: Request, x_jarvis_secret: Optional[str] = Header(default=None)):
    """Called by n8n every few minutes. Resends events that were not delivered."""
    check_secret(x_jarvis_secret, request)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=MIN_AGE_MINUTES)

    with SessionLocal(info={"system": True}) as db:  # serves every company
        ids = db.scalars(
            select(WorkflowEvent.id)
            .where(
                WorkflowEvent.status != "sent",
                WorkflowEvent.attempts < MAX_ATTEMPTS,
                WorkflowEvent.created_at < cutoff,
            )
            .order_by(WorkflowEvent.id)
            .limit(50)
        ).all()

    for event_id in ids:
        send_event(event_id)

    with SessionLocal(info={"system": True}) as db:  # serves every company
        gave_up = count(
            db, WorkflowEvent.status != "sent", WorkflowEvent.attempts >= MAX_ATTEMPTS
        )
        still_failing = count(db, WorkflowEvent.status != "sent")

    return {"retried": len(ids), "gave_up": gave_up, "still_failing": still_failing}
