from sqlalchemy import select

from app.db import SessionLocal
from app.events import send_event
from app.models import WorkflowEvent

with SessionLocal() as db:
    ids = db.scalars(
        select(WorkflowEvent.id).where(WorkflowEvent.status != "sent")
    ).all()

print(f"Retrying {len(ids)} events")
for event_id in ids:
    send_event(event_id)
print("Done")