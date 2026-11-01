import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.appointments import company_hours
from app.db import get_db
from app.events import send_event
from app.models import Company, Customer, SupportTicket, WorkflowEvent
from app.security import get_current_company
from app.tickets import TicketOut, find_by_key

router = APIRouter()


class EscalationCreate(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    customer_phone: Optional[str] = Field(default=None, max_length=30)


class EscalationResult(BaseModel):
    ticket: TicketOut
    already_existed: bool
    within_business_hours: bool


def is_open_now(company: Company) -> bool:
    now = datetime.now(ZoneInfo(company.timezone))
    open_hour, close_hour, _, closed = company_hours(company)
    return now.weekday() not in closed and open_hour <= now.hour < close_hour


@router.post("/escalations", response_model=EscalationResult)
def escalate_to_human(
    payload: EscalationCreate,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(..., min_length=8, max_length=100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Records an urgent request for a human and queues an alert event for the team."""
    open_now = is_open_now(company)

    existing = find_by_key(db, company.id, idempotency_key)
    if existing:
        return {"ticket": existing, "already_existed": True, "within_business_hours": open_now}

    customer = None
    if payload.customer_phone:
        cleaned = re.sub(r"[\s\-()]", "", payload.customer_phone)
        customer = db.scalar(
            select(Customer).where(
                Customer.company_id == company.id, Customer.phone == cleaned
            )
        )
        if customer is None:
            raise HTTPException(status_code=404, detail="Customer not found")

    ticket = SupportTicket(
        company_id=company.id,
        customer_id=customer.id if customer else None,
        subject="Human callback requested",
        description=payload.reason,
        priority="urgent",
        idempotency_key=idempotency_key,
    )
    db.add(ticket)

    try:
        db.flush()
        db.refresh(ticket)
        event = WorkflowEvent(
            company_id=company.id,
            ticket_id=ticket.id,
            event_type="escalation_created",
            payload={
                "company": {
                    "slug": company.slug,
                    "name": company.name,
                    "staff_email": company.staff_email,
                },
                "ticket": {
                    "id": ticket.id,
                    "subject": ticket.subject,
                    "description": ticket.description,
                    "priority": ticket.priority,
                    "status": ticket.status,
                },
                "customer": {
                    "name": customer.full_name if customer else None,
                    "phone": customer.phone if customer else None,
                },
                "within_business_hours": open_now,
            },
        )
        db.add(event)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = find_by_key(db, company.id, idempotency_key)
        if existing:
            return {"ticket": existing, "already_existed": True, "within_business_hours": open_now}
        raise HTTPException(status_code=409, detail="Could not record the request.")

    db.refresh(ticket)
    background_tasks.add_task(send_event, event.id)
    return {"ticket": ticket, "already_existed": False, "within_business_hours": open_now}
