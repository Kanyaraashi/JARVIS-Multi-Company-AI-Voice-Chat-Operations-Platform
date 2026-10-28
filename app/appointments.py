from datetime import date as Date
from datetime import datetime, timedelta
from datetime import time as Time
from typing import Optional
from zoneinfo import ZoneInfo
import re

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.events import send_event
from app.models import Appointment, Company, Customer, WorkflowEvent
from app.security import get_current_company

router = APIRouter()

# Simple opening rules for now. Later they move into each company's settings.
OPEN_HOUR = 9
CLOSE_HOUR = 18
SLOT_MINUTES = 30
CLOSED_WEEKDAYS = {6}  # 6 = Sunday


class AppointmentCreate(BaseModel):
    customer_phone: str = Field(min_length=5, max_length=30)
    date: Date
    time: Time
    reason: Optional[str] = Field(default=None, max_length=300)


class AppointmentOut(BaseModel):
    id: int
    status: str
    date: str
    time: str
    timezone: str
    reason: Optional[str] = None


class AppointmentResult(BaseModel):
    appointment: AppointmentOut
    already_existed: bool


class AvailabilityOut(BaseModel):
    date: str
    timezone: str
    open_slots: list[str]


def to_out(appt: Appointment, tz: ZoneInfo) -> dict:
    local = appt.starts_at.astimezone(tz)
    return {
        "id": appt.id,
        "status": appt.status,
        "date": local.strftime("%Y-%m-%d"),
        "time": local.strftime("%H:%M"),
        "timezone": str(tz),
        "reason": appt.reason,
    }


def day_slots(day: Date, tz: ZoneInfo) -> list[datetime]:
    """All bookable start times for one day in the company's timezone."""
    if day.weekday() in CLOSED_WEEKDAYS:
        return []
    slots = []
    current = datetime.combine(day, Time(OPEN_HOUR, 0), tzinfo=tz)
    end = datetime.combine(day, Time(CLOSE_HOUR, 0), tzinfo=tz)
    while current < end:
        slots.append(current)
        current += timedelta(minutes=SLOT_MINUTES)
    return slots


def find_by_key(db: Session, company_id: int, key: str):
    return db.scalar(
        select(Appointment).where(
            Appointment.company_id == company_id,
            Appointment.idempotency_key == key,
        )
    )


@router.get("/appointments/availability", response_model=AvailabilityOut)
def availability(
    date: Date = Query(...),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Lists the free time slots for one day."""
    tz = ZoneInfo(company.timezone)
    slots = day_slots(date, tz)

    booked = set()
    if slots:
        booked = set(
            db.scalars(
                select(Appointment.starts_at).where(
                    Appointment.company_id == company.id,
                    Appointment.status == "booked",
                    Appointment.starts_at >= slots[0],
                    Appointment.starts_at <= slots[-1],
                )
            ).all()
        )

    now = datetime.now(tz)
    open_slots = [s.strftime("%H:%M") for s in slots if s > now and s not in booked]
    return {"date": date.isoformat(), "timezone": str(tz), "open_slots": open_slots}


@router.post("/appointments", response_model=AppointmentResult)
def book_appointment(
    payload: AppointmentCreate,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(..., min_length=8, max_length=100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Books an appointment and queues a confirmation event for n8n."""
    tz = ZoneInfo(company.timezone)

    # Same request sent twice? Return the first booking, create nothing new.
    existing = find_by_key(db, company.id, idempotency_key)
    if existing:
        return {"appointment": to_out(existing, tz), "already_existed": True}

    start = datetime.combine(
        payload.date, payload.time.replace(tzinfo=None), tzinfo=tz
    )

    if start not in day_slots(payload.date, tz):
        raise HTTPException(
            status_code=422,
            detail="That is not a bookable time. Check availability first.",
        )
    if start <= datetime.now(tz):
        raise HTTPException(status_code=422, detail="That time is in the past.")

    cleaned = re.sub(r"[\s\-()]", "", payload.customer_phone)
    customer = db.scalar(
        select(Customer).where(
            Customer.company_id == company.id, Customer.phone == cleaned
        )
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    taken = db.scalar(
        select(Appointment.id).where(
            Appointment.company_id == company.id,
            Appointment.starts_at == start,
            Appointment.status == "booked",
        )
    )
    if taken:
        raise HTTPException(status_code=409, detail="That time slot is already booked.")

    appointment = Appointment(
        company_id=company.id,
        customer_id=customer.id,
        starts_at=start,
        ends_at=start + timedelta(minutes=SLOT_MINUTES),
        reason=payload.reason,
        idempotency_key=idempotency_key,
    )
    db.add(appointment)

    try:
        db.flush()
        db.refresh(appointment)

        event = WorkflowEvent(
            company_id=company.id,
            event_type="appointment_created",
            payload={
                "company": {
                    "slug": company.slug,
                    "name": company.name,
                    "agent_name": company.agent_name,
                },
                "appointment": {
                    "id": appointment.id,
                    "date": start.strftime("%A, %d %B %Y"),
                    "time": start.strftime("%I:%M %p"),
                    "reason": appointment.reason,
                },
                "customer": {"name": customer.full_name, "email": customer.email},
            },
        )
        db.add(event)
        db.commit()  # appointment and event are saved together, or not at all
    except IntegrityError:
        db.rollback()
        existing = find_by_key(db, company.id, idempotency_key)
        if existing:  # two identical requests raced each other
            return {"appointment": to_out(existing, tz), "already_existed": True}
        raise HTTPException(status_code=409, detail="That time slot is already booked.")

    db.refresh(appointment)
    # Runs after the response is sent, so the caller never waits for n8n.
    background_tasks.add_task(send_event, event.id)
    return {"appointment": to_out(appointment, tz), "already_existed": False}


@router.get("/appointments/{appointment_id}", response_model=AppointmentOut)
def get_appointment(
    appointment_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Returns an appointment, but only if it belongs to the key's company."""
    appointment = db.scalar(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.company_id == company.id,
        )
    )
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return to_out(appointment, ZoneInfo(company.timezone))


class ChangeResult(BaseModel):
    appointment: AppointmentOut
    changed: bool


class RescheduleBody(BaseModel):
    date: Date
    time: Time


def get_own_appointment(
    db: Session, company: Company, appointment_id: int
) -> Appointment:
    """Finds an appointment in this company only, and locks it while we change it."""
    appointment = db.scalar(
        select(Appointment)
        .where(
            Appointment.id == appointment_id,
            Appointment.company_id == company.id,
        )
        .with_for_update()
    )
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appointment


@router.post("/appointments/{appointment_id}/cancel", response_model=ChangeResult)
def cancel_appointment(
    appointment_id: int,
    background_tasks: BackgroundTasks,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Cancels a booked appointment and queues a cancellation email event."""
    tz = ZoneInfo(company.timezone)
    appointment = get_own_appointment(db, company, appointment_id)

    if appointment.status == "cancelled":  # already done, change nothing
        return {"appointment": to_out(appointment, tz), "changed": False}
    if appointment.status != "booked":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel an appointment that is {appointment.status}.",
        )

    customer = db.get(Customer, appointment.customer_id)
    local = appointment.starts_at.astimezone(tz)

    appointment.status = "cancelled"
    event = WorkflowEvent(
        company_id=company.id,
        event_type="appointment_cancelled",
        payload={
            "company": {
                "slug": company.slug,
                "name": company.name,
                "agent_name": company.agent_name,
            },
            "appointment": {
                "id": appointment.id,
                "date": local.strftime("%A, %d %B %Y"),
                "time": local.strftime("%I:%M %p"),
                "reason": appointment.reason,
            },
            "customer": {"name": customer.full_name, "email": customer.email},
        },
    )
    db.add(event)
    db.commit()  # the cancellation and its event are saved together

    db.refresh(appointment)
    background_tasks.add_task(send_event, event.id)
    return {"appointment": to_out(appointment, tz), "changed": True}


@router.post("/appointments/{appointment_id}/reschedule", response_model=ChangeResult)
def reschedule_appointment(
    appointment_id: int,
    payload: RescheduleBody,
    background_tasks: BackgroundTasks,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Moves a booked appointment to a new free slot and queues an email event."""
    tz = ZoneInfo(company.timezone)
    appointment = get_own_appointment(db, company, appointment_id)

    if appointment.status != "booked":
        raise HTTPException(
            status_code=409, detail="Only booked appointments can be rescheduled."
        )

    new_start = datetime.combine(
        payload.date, payload.time.replace(tzinfo=None), tzinfo=tz
    )

    if new_start == appointment.starts_at:  # already at that time, change nothing
        return {"appointment": to_out(appointment, tz), "changed": False}

    if new_start not in day_slots(payload.date, tz):
        raise HTTPException(
            status_code=422,
            detail="That is not a bookable time. Check availability first.",
        )
    if new_start <= datetime.now(tz):
        raise HTTPException(status_code=422, detail="That time is in the past.")

    taken = db.scalar(
        select(Appointment.id).where(
            Appointment.company_id == company.id,
            Appointment.starts_at == new_start,
            Appointment.status == "booked",
        )
    )
    if taken:
        raise HTTPException(status_code=409, detail="That time slot is already booked.")

    customer = db.get(Customer, appointment.customer_id)
    old_local = appointment.starts_at.astimezone(tz)

    appointment.starts_at = new_start
    appointment.ends_at = new_start + timedelta(minutes=SLOT_MINUTES)
    event = WorkflowEvent(
        company_id=company.id,
        event_type="appointment_rescheduled",
        payload={
            "company": {
                "slug": company.slug,
                "name": company.name,
                "agent_name": company.agent_name,
            },
            "appointment": {
                "id": appointment.id,
                "old_date": old_local.strftime("%A, %d %B %Y"),
                "old_time": old_local.strftime("%I:%M %p"),
                "date": new_start.strftime("%A, %d %B %Y"),
                "time": new_start.strftime("%I:%M %p"),
                "reason": appointment.reason,
            },
            "customer": {"name": customer.full_name, "email": customer.email},
        },
    )
    db.add(event)

    try:
        db.commit()  # the move and its event are saved together
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That time slot is already booked.")

    db.refresh(appointment)
    background_tasks.add_task(send_event, event.id)
    return {"appointment": to_out(appointment, tz), "changed": True}