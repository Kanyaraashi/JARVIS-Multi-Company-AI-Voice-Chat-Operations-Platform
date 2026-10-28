import re
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.events import send_event
from app.models import Company, Customer, SupportTicket, WorkflowEvent
from app.security import get_current_company

router = APIRouter()


class TicketCreate(BaseModel):
    subject: str = Field(min_length=3, max_length=300)
    description: str = Field(min_length=3, max_length=5000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    customer_phone: Optional[str] = Field(default=None, max_length=30)


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject: str
    description: str
    status: str
    priority: str
    customer_id: Optional[int] = None


class TicketResult(BaseModel):
    ticket: TicketOut
    already_existed: bool


def find_by_key(db: Session, company_id: int, key: str):
    return db.scalar(
        select(SupportTicket).where(
            SupportTicket.company_id == company_id,
            SupportTicket.idempotency_key == key,
        )
    )


@router.post("/tickets", response_model=TicketResult)
def create_ticket(
    payload: TicketCreate,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(..., min_length=8, max_length=100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Creates a ticket for the key's company and queues an n8n event."""
    # Same request sent twice? Return the first ticket, create nothing new.
    existing = find_by_key(db, company.id, idempotency_key)
    if existing:
        return {"ticket": existing, "already_existed": True}

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
        subject=payload.subject,
        description=payload.description,
        priority=payload.priority,
        idempotency_key=idempotency_key,
    )
    db.add(ticket)

    try:
        db.flush()  # gives the ticket its id
        db.refresh(ticket)

        event = WorkflowEvent(
            company_id=company.id,
            ticket_id=ticket.id,
            event_type="ticket_created",
            payload={
                "company": {"slug": company.slug, "name": company.name},
                "ticket": {
                    "id": ticket.id,
                    "subject": ticket.subject,
                    "description": ticket.description,
                    "priority": ticket.priority,
                    "status": ticket.status,
                },
                "customer_name": customer.full_name if customer else None,
            },
        )
        db.add(event)
        db.commit()  # ticket and event are saved together, or not at all
    except IntegrityError:
        db.rollback()
        existing = find_by_key(db, company.id, idempotency_key)
        if existing:  # two identical requests raced each other
            return {"ticket": existing, "already_existed": True}
        raise HTTPException(status_code=409, detail="Could not create ticket")

    db.refresh(ticket)
    # Runs after the response is sent, so the caller never waits for n8n.
    background_tasks.add_task(send_event, event.id)
    return {"ticket": ticket, "already_existed": False}


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
def get_ticket(
    ticket_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Returns a ticket, but only if it belongs to the key's company."""
    ticket = db.scalar(
        select(SupportTicket).where(
            SupportTicket.id == ticket_id,
            SupportTicket.company_id == company.id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket