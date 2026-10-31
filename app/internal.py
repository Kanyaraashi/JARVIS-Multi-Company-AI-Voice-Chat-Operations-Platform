import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import func, select

from app.db import SessionLocal
from app.events import send_event
from app.models import WorkflowEvent

router = APIRouter(prefix="/internal")

MAX_ATTEMPTS = 5
MIN_AGE_MINUTES = 1


def check_secret(provided: Optional[str]) -> None:
    secret = os.getenv("N8N_WEBHOOK_SECRET")
    if not secret or not provided or not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=401, detail="Invalid secret")


def count(db, *conditions) -> int:
    return (
        db.scalar(select(func.count()).select_from(WorkflowEvent).where(*conditions)) or 0
    )


@router.post("/retry-events")
def retry_events(x_jarvis_secret: Optional[str] = Header(default=None)):
    """Called by n8n every few minutes. Resends events that were not delivered."""
    check_secret(x_jarvis_secret)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=MIN_AGE_MINUTES)

    with SessionLocal() as db:
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

    with SessionLocal() as db:
        gave_up = count(
            db, WorkflowEvent.status != "sent", WorkflowEvent.attempts >= MAX_ATTEMPTS
        )
        still_failing = count(db, WorkflowEvent.status != "sent")

    return {"retried": len(ids), "gave_up": gave_up, "still_failing": still_failing}