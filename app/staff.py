from datetime import datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
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


# ---------- company settings ----------

class CompanySettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    slug: str
    name: str
    timezone: str
    staff_email: Optional[str] = None
    open_hour: int
    close_hour: int
    slot_minutes: int
    closed_weekdays: list[int]


class SettingsPatch(BaseModel):
    """Send only the fields you want to change. staff_email: null removes it."""

    staff_email: Optional[str] = Field(
        default=None, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    open_hour: int = Field(default=9, ge=0, le=23)
    close_hour: int = Field(default=18, ge=1, le=24)
    slot_minutes: Literal[10, 15, 20, 30, 45, 60] = 30
    closed_weekdays: list[Literal[0, 1, 2, 3, 4, 5, 6]] = Field(default_factory=list)
    timezone: str = Field(default="Asia/Kolkata", max_length=50)


@router.get("/company", response_model=CompanySettings)
def get_settings(company: Company = Depends(get_staff_company)):
    """Shows this company's settings."""
    return company


@router.patch("/company", response_model=CompanySettings)
def update_settings(
    payload: SettingsPatch,
    company: Company = Depends(get_staff_company),
    db: Session = Depends(get_db),
):
    """Changes this company's settings. Only the fields you send are changed."""
    changes = payload.model_dump(exclude_unset=True)
    if "closed_weekdays" in changes:
        changes["closed_weekdays"] = sorted(set(changes["closed_weekdays"]))
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(status_code=422, detail="Unknown timezone, for example Asia/Kolkata.")

    new_open = changes.get("open_hour", company.open_hour)
    new_close = changes.get("close_hour", company.close_hour)
    if new_open >= new_close:
        raise HTTPException(status_code=422, detail="open_hour must be before close_hour.")

    company = db.merge(company)
    for field, value in changes.items():
        setattr(company, field, value)
    db.commit()
    db.refresh(company)
    return company
