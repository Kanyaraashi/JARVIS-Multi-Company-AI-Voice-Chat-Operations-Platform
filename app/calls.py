"""Call records (Step 24) and call latency reports (Step 25).

The voice agent saves one record when a call ends (POST /calls, AI key).
Staff read them (GET /staff/calls..., staff key). Nothing here ever returns another
company's calls, and the database enforces that again with row-level security.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from app import audit
from app.db import get_db
from app.latency import summarize
from app.models import CallRecord, Company, Customer
from app.privacy import redact
from app.security import get_current_company, get_staff_company

router = APIRouter()

MAX_CALL_HOURS = 6
Outcome = Literal["completed", "handoff", "abandoned", "failed"]


class TranscriptLine(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)


class ToolUse(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    ok: bool


class TurnLatency(BaseModel):
    total_ms: Optional[int] = Field(default=None, ge=0, le=600_000)
    listen_ms: Optional[int] = Field(default=None, ge=0, le=600_000)
    think_ms: Optional[int] = Field(default=None, ge=0, le=600_000)
    speak_ms: Optional[int] = Field(default=None, ge=0, le=600_000)
    source: Optional[Literal["measured", "estimated"]] = None
    llm_real_ms: Optional[int] = Field(default=None, ge=0, le=600_000)  # the model's own time
    filler: Optional[bool] = None      # the caller heard "One moment please."
    switched: Optional[bool] = None    # a backup model answered


class CallCreate(BaseModel):
    room_name: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.:\-]+$")
    direction: Literal["inbound", "outbound", "web"]
    caller_phone: Optional[str] = Field(default=None, max_length=40)
    started_at: datetime
    ended_at: datetime
    outcome: Outcome
    transcript: list[TranscriptLine] = Field(default_factory=list, max_length=400)
    tools_used: list[ToolUse] = Field(default_factory=list, max_length=100)
    latency_turns: list[TurnLatency] = Field(default_factory=list, max_length=400)
    providers: dict[str, str] = Field(default_factory=dict, max_length=10)

    @field_validator("started_at", "ended_at")
    @classmethod
    def must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("must include a time zone, for example 2026-11-01T10:00:00+00:00")
        return value

    @field_validator("providers")
    @classmethod
    def short_provider_text(cls, value: dict) -> dict:
        for key, text in value.items():
            if len(key) > 30 or len(text) > 80:
                raise ValueError("provider names are too long")
        return value


class CallCreated(BaseModel):
    id: int
    already_existed: bool
    outcome: str
    duration_seconds: int
    turn_count: int


def clean_caller_phone(raw: Optional[str]) -> Optional[str]:
    """SIP callers can be 'anonymous' or 'restricted'. Anything that is not a phone
    number is simply not stored; the call itself is still recorded."""
    if not raw:
        return None
    phone = re.sub(r"[\s\-()]", "", raw)
    return phone if re.fullmatch(r"\+?\d{7,15}", phone) else None


@router.post("/calls", response_model=CallCreated)
def record_call(
    payload: CallCreate,
    request: Request,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Saves a finished call. Safe to send twice: the same room is saved only once."""
    now = datetime.now(timezone.utc)
    if payload.ended_at < payload.started_at:
        raise HTTPException(status_code=422, detail="The call cannot end before it started.")
    if payload.ended_at - payload.started_at > timedelta(hours=MAX_CALL_HOURS):
        raise HTTPException(status_code=422, detail=f"Calls longer than {MAX_CALL_HOURS} hours are not accepted.")
    if payload.started_at > now + timedelta(minutes=10):
        raise HTTPException(status_code=422, detail="The call cannot start in the future.")

    turn_count = sum(1 for line in payload.transcript if line.role == "user")
    if payload.outcome == "abandoned" and turn_count > 0:
        raise HTTPException(status_code=422, detail="An abandoned call cannot have caller speech.")
    transferred = any(t.name == "transfer_to_human" and t.ok for t in payload.tools_used)
    if payload.outcome == "handoff" and not transferred:
        raise HTTPException(
            status_code=422,
            detail="A handoff call needs a successful transfer_to_human in tools_used.",
        )

    existing = db.scalar(
        select(CallRecord).where(
            CallRecord.company_id == company.id, CallRecord.room_name == payload.room_name
        )
    )
    if existing:
        return _created(existing, True)

    phone = clean_caller_phone(payload.caller_phone)
    customer = None
    if phone:
        customer = db.scalar(
            select(Customer).where(Customer.company_id == company.id, Customer.phone == phone)
        )

    record = CallRecord(
        company_id=company.id,
        room_name=payload.room_name,
        direction=payload.direction,
        caller_phone=phone,
        customer_id=customer.id if customer else None,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        duration_seconds=int((payload.ended_at - payload.started_at).total_seconds()),
        outcome=payload.outcome,
        turn_count=turn_count,
        transcript=[{"role": l.role, "text": redact(l.text)} for l in payload.transcript],
        tools_used=[t.model_dump() for t in payload.tools_used],
        latency_turns=[t.model_dump(exclude_none=True) for t in payload.latency_turns],
        providers=payload.providers,
    )
    db.add(record)
    try:
        db.flush()
        audit.record(
            db, request, company, "call.record", "call", record.id,
            {"outcome": record.outcome, "duration_seconds": record.duration_seconds},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(CallRecord).where(
                CallRecord.company_id == company.id, CallRecord.room_name == payload.room_name
            )
        )
        if existing:  # two identical requests raced each other
            return _created(existing, True)
        raise HTTPException(status_code=409, detail="Could not save the call.")

    db.refresh(record)
    return _created(record, False)


def _created(record: CallRecord, already: bool) -> dict:
    return {
        "id": record.id,
        "already_existed": already,
        "outcome": record.outcome,
        "duration_seconds": record.duration_seconds,
        "turn_count": record.turn_count,
    }


# ---------- staff views ----------

class CallSummary(BaseModel):
    id: int
    room_name: str
    direction: str
    started_at: datetime
    duration_seconds: int
    outcome: str
    turn_count: int
    caller_phone: Optional[str] = None
    customer_name: Optional[str] = None
    latency: dict


class CallDetail(CallSummary):
    transcript: list
    tools_used: list
    providers: dict


def _summary(record: CallRecord, customer_name: Optional[str], target_ms: int) -> dict:
    return {
        "id": record.id,
        "room_name": record.room_name,
        "direction": record.direction,
        "started_at": record.started_at,
        "duration_seconds": record.duration_seconds,
        "outcome": record.outcome,
        "turn_count": record.turn_count,
        "caller_phone": record.caller_phone,
        "customer_name": customer_name,
        "latency": summarize(record.latency_turns, target_ms),
    }


def _customer_join():
    return and_(
        Customer.company_id == CallRecord.company_id, Customer.id == CallRecord.customer_id
    )


@router.get("/staff/calls", response_model=list[CallSummary])
def list_calls(
    limit: int = Query(default=50, ge=1, le=100),
    outcome: Optional[Outcome] = Query(default=None),
    company: Company = Depends(get_staff_company),
    db: Session = Depends(get_db),
):
    """The latest calls of this company, newest first (without transcripts)."""
    query = (
        select(CallRecord, Customer.full_name)
        .outerjoin(Customer, _customer_join())
        .where(CallRecord.company_id == company.id)
        .options(defer(CallRecord.transcript))
    )
    if outcome:
        query = query.where(CallRecord.outcome == outcome)
    rows = db.execute(query.order_by(CallRecord.id.desc()).limit(limit)).all()
    return [_summary(record, name, 1500) for record, name in rows]


@router.get("/staff/calls/latency")
def latency_report(
    calls: int = Query(default=50, ge=1, le=200, description="How many recent calls to include"),
    target_ms: int = Query(default=1500, ge=200, le=10000),
    company: Company = Depends(get_staff_company),
    db: Session = Depends(get_db),
):
    """How long callers waited for answers, over this company's recent calls."""
    rows = db.scalars(
        select(CallRecord.latency_turns)
        .where(CallRecord.company_id == company.id)
        .order_by(CallRecord.id.desc())
        .limit(calls)
    ).all()
    turns = [turn for call_turns in rows for turn in call_turns]
    return {"calls_included": len(rows), **summarize(turns, target_ms)}


@router.get("/staff/calls/{call_id}", response_model=CallDetail)
def call_detail(
    call_id: int,
    company: Company = Depends(get_staff_company),
    db: Session = Depends(get_db),
):
    """One call with its (masked) transcript."""
    row = db.execute(
        select(CallRecord, Customer.full_name)
        .outerjoin(Customer, _customer_join())
        .where(CallRecord.id == call_id, CallRecord.company_id == company.id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Call not found")
    record, name = row
    return {
        **_summary(record, name, 1500),
        "transcript": record.transcript,
        "tools_used": record.tools_used,
        "providers": record.providers,
    }
