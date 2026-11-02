import os

import httpx
from dotenv import load_dotenv

from app.db import SessionLocal
from app.models import WorkflowEvent

load_dotenv()

WEBHOOK_URLS = {
    "ticket_created": os.getenv("N8N_TICKET_WEBHOOK_URL"),
    "ticket_updated": os.getenv("N8N_TICKET_UPDATED_WEBHOOK_URL"),
    "escalation_created": os.getenv("N8N_ESCALATION_WEBHOOK_URL"),
    "appointment_created": os.getenv("N8N_APPOINTMENT_WEBHOOK_URL"),
    "appointment_cancelled": os.getenv("N8N_APPOINTMENT_CANCELLED_WEBHOOK_URL"),
    "appointment_rescheduled": os.getenv("N8N_APPOINTMENT_RESCHEDULED_WEBHOOK_URL"),
    "invoice_requested": os.getenv("N8N_INVOICE_WEBHOOK_URL"),
}
SECRET = os.getenv("N8N_WEBHOOK_SECRET")


def send_event(event_id: int) -> None:
    """Sends one saved event to n8n and records whether it worked."""
    with SessionLocal(info={"system": True}) as db:  # serves every company
        event = db.get(WorkflowEvent, event_id)
        if event is None or event.status == "sent":
            return

        event.attempts += 1
        url = WEBHOOK_URLS.get(event.event_type)

        if not url or not SECRET:
            event.status = "failed"
            event.last_error = "Webhook URL or secret is not configured"
            db.commit()
            return

        body = {"event_id": event.id, "event_type": event.event_type, **event.payload}

        try:
            response = httpx.post(
                url, json=body, headers={"X-Jarvis-Secret": SECRET}, timeout=10
            )
            if response.status_code >= 400:
                raise RuntimeError(f"n8n returned {response.status_code}")
            event.status = "sent"
            event.last_error = None
        except Exception as exc:
            event.status = "failed"
            event.last_error = str(exc)[:500]

        db.commit()
