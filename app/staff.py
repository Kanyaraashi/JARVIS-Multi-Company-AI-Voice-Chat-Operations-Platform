from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.events import send_event
from app.models import Company, Customer, SupportTicket, TicketUpdate, WorkflowEvent
from app.security import get_staff_company

router = APIRouter(prefix="/staff")


class StaffTicket(BaseModel):
    id: int
    subject: str
    description: str
    status: str
    priority: str
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    created_at: datetime


class TicketPatch(BaseModel):
    status: Literal["in_progress", "resolved", "closed"]
    note: Optional[str] = Field(default=None, max_length=1000)


class PatchResult(BaseModel):
    ticket: StaffTicket
    changed: bool


def to_staff(ticket: SupportTicket, customer: Optional[Customer]) -> dict:
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "description": ticket.description,
        "status": ticket.status,
        "priority": ticket.priority,
        "customer_name": customer.full_name if customer else None,
        "customer_phone": customer.phone if customer else None,
        "created_at": ticket.created_at,
    }


@router.get("/tickets", response_model=list[StaffTicket])
def list_tickets(
    status: Optional[Literal["open", "in_progress", "resolved", "closed"]] = Query(default=None),
    company: Company = Depends(get_staff_company),
    db: Session = Depends(get_db),
):
    """Lists the latest 50 tickets of this company."""
    query = select(SupportTicket).where(SupportTicket.company_id == company.id)
    if status:
        query = query.where(SupportTicket.status == status)
    tickets = db.scalars(query.order_by(SupportTicket.id.desc()).limit(50)).all()

    result = []
    for ticket in tickets:
        customer = db.get(Customer, ticket.customer_id) if ticket.customer_id else None
        result.append(to_staff(ticket, customer))
    return result


@router.patch("/tickets/{ticket_id}", response_model=PatchResult)
def update_ticket(
    ticket_id: int,
    payload: TicketPatch,
    background_tasks: BackgroundTasks,
    company: Company = Depends(get_staff_company),
    db: Session = Depends(get_db),
):
    """Changes a ticket's status, saves the history and queues a customer email event."""
    ticket = db.scalar(
        select(SupportTicket)
        .where(SupportTicket.id == ticket_id, SupportTicket.company_id == company.id)
        .with_for_update()
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    customer = db.get(Customer, ticket.customer_id) if ticket.customer_id else None
    note = (payload.note or "").strip() or None

    if ticket.status == payload.status:  # nothing to change, so no email
        return {"ticket": to_staff(ticket, customer), "changed": False}
    if ticket.status == "closed":
        raise HTTPException(status_code=409, detail="A closed ticket cannot be changed.")

    old_status = ticket.status
    ticket.status = payload.status
    db.add(
        TicketUpdate(
            company_id=company.id,
            ticket_id=ticket.id,
            old_status=old_status,
            new_status=payload.status,
            note=note,
        )
    )
    event = WorkflowEvent(
        company_id=company.id,
        ticket_id=ticket.id,
        event_type="ticket_updated",
        payload={
            "company": {"slug": company.slug, "name": company.name},
            "ticket": {
                "id": ticket.id,
                "subject": ticket.subject,
                "status": payload.status,
            },
            "note": note,
            "customer": {
                "name": customer.full_name if customer else None,
                "email": customer.email if customer else None,
            },
        },
    )
    db.add(event)
    db.commit()  # the change, its history and the event are saved together

    db.refresh(ticket)
    background_tasks.add_task(send_event, event.id)
    return {"ticket": to_staff(ticket, customer), "changed": True}