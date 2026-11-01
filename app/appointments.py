from datetime import date as Date
from datetime import datetime, timedelta
from datetime import time as Time
from typing import Optional
from zoneinfo import ZoneInfo
import re

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.events import send_event
from app.models import Appointment, Company, Customer, WorkflowEvent
from app.security import get_current_company

router = APIRouter()

# Defaults, used only when a company has no value of its own.
# Each company's real settings live in the companies table (see /staff/company).
OPEN_HOUR = 9
CLOSE_HOUR = 18
SLOT_MINUTES = 30
CLOSED_WEEKDAYS = {6}  # 6 = Sunday


def company_hours(company: Company) -> tuple[int, int, int, set[int]]:
    """open hour, close hour, slot length in minutes, closed weekdays of one company."""
    return (
        company.open_hour if company.open_hour is not None else OPEN_HOUR,
        company.close_hour if company.close_hour is not None else CLOSE_HOUR,
        company.slot_minutes if company.slot_minutes is not None else SLOT_MINUTES,
        set(company.closed_weekdays) if company.closed_weekdays is not None else CLOSED_WEEKDAYS,
    )


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


def day_slots(day: Date, company: Company) -> list[datetime]:
    """All bookable start times for one day, using this company's own settings."""
    tz = ZoneInfo(company.timezone)
    open_hour, close_hour, slot_minutes, closed = company_hours(company)
    if day.weekday() in closed:
        return []
    slots = []
    current = datetime.combine(day, Time(open_hour, 0), tzinfo=tz)
    end = datetime.combine(day, Time(0, 0), tzinfo=tz) + timedelta(hours=close_hour)
    while current + timedelta(minutes=slot_minutes) <= end:
        slots.append(current)
        current += timedelta(minutes=slot_minutes)
    return slots


def slot_taken(db: Session, company: Company, start: datetime, end: datetime, ignore_id=None):
    """Is any booked appointment of this company overlapping start..end?"""
    query = select(Appointment.id).where(
        Appointment.company_id == company.id,
        Appointment.status == "booked",
        Appointment.starts_at < end,
        Appointment.ends_at > start,
    )
    if ignore_id is not None:
        query = query.where(Appointment.id != ignore_id)
    return db.scalar(query.limit(1))


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
    _, _, slot_minutes, _ = company_hours(company)
    slots = day_slots(date, company)

    booked = []
    if slots:
        window_end = slots[-1] + timedelta(minutes=slot_minutes)
        booked = db.execute(
            select(Appointment.starts_at, Appointment.ends_at).where(
                Appointment.company_id == company.id,
                Appointment.status == "booked",
                Appointment.starts_at < window_end,
                Appointment.ends_at > slots[0],
            )
        ).all()

    now = datetime.now(tz)
    length = timedelta(minutes=slot_minutes)
    open_slots = [
        s.strftime("%H:%M")
        for s in slots
        if s > now and not any(b.starts_at < s + length and b.ends_at > s for b in booked)
    ]
    return {"date": date.isoformat(), "timezone": str(tz), "open_slots": open_slots}


@router.post("/appointments", response_model=AppointmentResult)
def book_appointment(
    payload: AppointmentCreate,
    request: Request,
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

    if start not in day_slots(payload.date, company):
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

    _, _, slot_minutes, _ = company_hours(company)
    end = start + timedelta(minutes=slot_minutes)
    if slot_taken(db, company, start, end):
        raise HTTPException(status_code=409, detail="That time slot is already booked.")

    appointment = Appointment(
        company_id=company.id,
        customer_id=customer.id,
        starts_at=start,
        ends_at=end,
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
        audit.record(
            db, request, company, "appointment.book", "appointment", appointment.id,
            {"starts_at": start.isoformat()},
        )
        db.commit()  # appointment, event and audit record are saved together, or not at all
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


class CancelBody(BaseModel):
    customer_phone: str = Field(min_length=5, max_length=30)


class RescheduleBody(BaseModel):
    customer_phone: str = Field(min_length=5, max_length=30)
    date: Date
    time: Time


def get_own_appointment(
    db: Session, company: Company, appointment_id: int, customer_phone: str
) -> Appointment:
    """Finds an appointment that belongs to THIS customer of THIS company, and locks it."""
    cleaned = re.sub(r"[\s\-()]", "", customer_phone)
    customer = db.scalar(
        select(Customer).where(
            Customer.company_id == company.id, Customer.phone == cleaned
        )
    )
    appointment = None
    if customer is not None:
        appointment = db.scalar(
            select(Appointment)
            .where(
                Appointment.id == appointment_id,
                Appointment.company_id == company.id,
                Appointment.customer_id == customer.id,
            )
            .with_for_update()
        )
    if appointment is None:
        raise HTTPException(
            status_code=404, detail="Appointment not found for this customer"
        )
    return appointment


@router.get("/customers/appointments", response_model=list[AppointmentOut])
def customer_appointments(
    phone: str = Query(..., min_length=5, max_length=30),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Lists the upcoming booked appointments of one customer of this company."""
    tz = ZoneInfo(company.timezone)
    cleaned = re.sub(r"[\s\-()]", "", phone)
    customer = db.scalar(
        select(Customer).where(
            Customer.company_id == company.id, Customer.phone == cleaned
        )
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    appointments = db.scalars(
        select(Appointment)
        .where(
            Appointment.company_id == company.id,
            Appointment.customer_id == customer.id,
            Appointment.status == "booked",
            Appointment.starts_at > datetime.now(tz),
        )
        .order_by(Appointment.starts_at)
    ).all()
    return [to_out(a, tz) for a in appointments]


@router.post("/appointments/{appointment_id}/cancel", response_model=ChangeResult)
def cancel_appointment(
    appointment_id: int,
    payload: CancelBody,
    request: Request,
    background_tasks: BackgroundTasks,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Cancels a booked appointment of this customer and queues an email event."""
    tz = ZoneInfo(company.timezone)
    appointment = get_own_appointment(db, company, appointment_id, payload.customer_phone)

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
    audit.record(db, request, company, "appointment.cancel", "appointment", appointment.id)
    db.commit()  # the cancellation, its event and audit record are saved together

    db.refresh(appointment)
    background_tasks.add_task(send_event, event.id)
    return {"appointment": to_out(appointment, tz), "changed": True}


@router.post("/appointments/{appointment_id}/reschedule", response_model=ChangeResult)
def reschedule_appointment(
    appointment_id: int,
    payload: RescheduleBody,
    request: Request,
    background_tasks: BackgroundTasks,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Moves a booked appointment of this customer to a new free slot."""
    tz = ZoneInfo(company.timezone)
    appointment = get_own_appointment(db, company, appointment_id, payload.customer_phone)

    if appointment.status != "booked":
        raise HTTPException(
            status_code=409, detail="Only booked appointments can be rescheduled."
        )

    new_start = datetime.combine(
        payload.date, payload.time.replace(tzinfo=None), tzinfo=tz
    )

    if new_start == appointment.starts_at:  # already at that time, change nothing
        return {"appointment": to_out(appointment, tz), "changed": False}

    if new_start not in day_slots(payload.date, company):
        raise HTTPException(
            status_code=422,
            detail="That is not a bookable time. Check availability first.",
        )
    if new_start <= datetime.now(tz):
        raise HTTPException(status_code=422, detail="That time is in the past.")

    _, _, slot_minutes, _ = company_hours(company)
    new_end = new_start + timedelta(minutes=slot_minutes)
    if slot_taken(db, company, new_start, new_end, ignore_id=appointment.id):
        raise HTTPException(status_code=409, detail="That time slot is already booked.")

    customer = db.get(Customer, appointment.customer_id)
    old_local = appointment.starts_at.astimezone(tz)

    appointment.starts_at = new_start
    appointment.ends_at = new_end
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
    audit.record(
        db, request, company, "appointment.reschedule", "appointment", appointment.id,
        {"from": old_local.isoformat(), "to": new_start.isoformat()},
    )

    try:
        db.commit()  # the move, its event and audit record are saved together
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That time slot is already booked.")

    db.refresh(appointment)
    background_tasks.add_task(send_event, event.id)
    return {"appointment": to_out(appointment, tz), "changed": True}
