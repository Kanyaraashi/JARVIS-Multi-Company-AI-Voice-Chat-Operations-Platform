from datetime import datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.events import send_event
from app.models import (
    AuditLog,
    Company,
    Customer,
    SupportTicket,
    TicketUpdate,
    WorkflowEvent,
)
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
    customer_email: Optional[str] = None
    # The newest "your ticket changed" email for this ticket: sent, failed, pending or None (no email yet).
    # "sent" means n8n accepted it. Whether the mailbox received it is up to the n8n email step.
    update_email: Optional[Literal["sent", "failed", "pending"]] = None
    created_at: datetime


class TicketPatch(BaseModel):
    status: Literal["in_progress", "resolved", "closed"]
    note: Optional[str] = Field(default=None, max_length=1000)


class PatchResult(BaseModel):
    ticket: StaffTicket
    changed: bool


def email_state(status: Optional[str]) -> Optional[str]:
    if status is None:
        return None
    return status if status in ("sent", "failed") else "pending"


def to_staff(ticket: SupportTicket, customer: Optional[Customer], update_email: Optional[str] = None) -> dict:
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "description": ticket.description,
        "status": ticket.status,
        "priority": ticket.priority,
        "customer_name": customer.full_name if customer else None,
        "customer_phone": customer.phone if customer else None,
        "customer_email": customer.email if customer else None,
        "update_email": email_state(update_email),
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

    latest_email = {}   # ticket id -> status of its newest status email (events are read oldest first)
    if tickets:
        rows = db.execute(
            select(WorkflowEvent.ticket_id, WorkflowEvent.status)
            .where(
                WorkflowEvent.company_id == company.id,
                WorkflowEvent.event_type == "ticket_updated",
                WorkflowEvent.ticket_id.in_([t.id for t in tickets]),
            )
            .order_by(WorkflowEvent.id)
        ).all()
        latest_email = {ticket_id: status for ticket_id, status in rows}

    result = []
    for ticket in tickets:
        customer = db.get(Customer, ticket.customer_id) if ticket.customer_id else None
        result.append(to_staff(ticket, customer, latest_email.get(ticket.id)))
    return result


@router.patch("/tickets/{ticket_id}", response_model=PatchResult)
def update_ticket(
    ticket_id: int,
    payload: TicketPatch,
    request: Request,
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
        newest = db.scalar(
            select(WorkflowEvent.status)
            .where(WorkflowEvent.company_id == company.id, WorkflowEvent.ticket_id == ticket.id,
                   WorkflowEvent.event_type == "ticket_updated")
            .order_by(WorkflowEvent.id.desc())
        )
        return {"ticket": to_staff(ticket, customer, newest), "changed": False}
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
    audit.record(
        db, request, company, "ticket.status_update", "ticket", ticket.id,
        {"from": old_status, "to": payload.status},
    )
    db.commit()  # the change, its history, the event and the audit record are saved together

    db.refresh(ticket)
    background_tasks.add_task(send_event, event.id)
    return {"ticket": to_staff(ticket, customer, "pending"), "changed": True}


@router.post("/tickets/{ticket_id}/resend-email")
def resend_ticket_email(
    ticket_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    company: Company = Depends(get_staff_company),
    db: Session = Depends(get_db),
):
    """Sends the newest status email of a ticket again, but only if it did not go out the first time."""
    ticket = db.scalar(
        select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.company_id == company.id)
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    event = db.scalar(
        select(WorkflowEvent)
        .where(WorkflowEvent.company_id == company.id, WorkflowEvent.ticket_id == ticket.id,
               WorkflowEvent.event_type == "ticket_updated")
        .order_by(WorkflowEvent.id.desc())
    )
    if event is None:
        raise HTTPException(status_code=404, detail="No status email has been queued for this ticket yet.")
    if event.status == "sent":
        raise HTTPException(status_code=409, detail="That email was already sent. Nothing to resend.")
    audit.record(db, request, company, "ticket.resend_email", "ticket", ticket.id, {"event_id": event.id})
    db.commit()
    background_tasks.add_task(send_event, event.id)
    return {"queued": True, "event_id": event.id}


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
    request: Request,
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
    before = {field: getattr(company, field) for field in changes}
    for field, value in changes.items():
        setattr(company, field, value)
    audit.record(
        db, request, company, "company.settings_update", "company", company.id,
        {"before": before, "after": changes},
    )
    db.commit()
    db.refresh(company)
    return company


# ---------- audit trail ----------

class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    actor_type: Optional[str] = None
    actor_label: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    details: Optional[dict] = None
    ip: Optional[str] = None


@router.get("/audit", response_model=list[AuditEntry])
def audit_trail(
    limit: int = Query(default=50, ge=1, le=200),
    action: Optional[str] = Query(default=None, max_length=60),
    company: Company = Depends(get_staff_company),
    db: Session = Depends(get_db),
):
    """Who changed what in this company, newest first."""
    query = select(AuditLog).where(AuditLog.company_id == company.id)
    if action:
        query = query.where(AuditLog.action == action)
    return db.scalars(query.order_by(AuditLog.id.desc()).limit(limit)).all()
