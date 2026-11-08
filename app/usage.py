"""How many call minutes a company used this month, and its cap (Step 32).

GET /company/usage   (AI key)    the voice worker asks this before it answers a call
GET /staff/usage     (staff)     shown to the company
The cap itself is set only by YOU, the platform owner (python -m app.owner cap ...), never by the customer.
Several calls at the same moment can overshoot the cap slightly: it is checked when a call starts.
"""
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CallRecord, Company
from app.security import get_current_company, get_staff_company

router = APIRouter()


class Usage(BaseModel):
    month: str                       # for example 2026-11, in the company's time zone
    used_minutes: float
    cap_minutes: Optional[int]       # None = no limit
    percent: Optional[int]
    calls: int
    allowed: bool


def month_window(company: Company, now: datetime):
    try:
        zone = ZoneInfo(company.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("Asia/Kolkata")
    local = now.astimezone(zone)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = (start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1))
    return start.strftime("%Y-%m"), start.astimezone(timezone.utc), nxt.astimezone(timezone.utc)


def usage_for(db: Session, company: Company, now: Optional[datetime] = None) -> Usage:
    now = now or datetime.now(timezone.utc)
    label, start, end = month_window(company, now)
    seconds, calls = db.execute(
        select(func.coalesce(func.sum(CallRecord.duration_seconds), 0), func.count())
        .where(CallRecord.company_id == company.id, CallRecord.started_at >= start, CallRecord.started_at < end)
    ).one()
    used = round(int(seconds) / 60, 1)
    cap = company.monthly_minutes_cap
    percent = None if cap in (None, 0) else int(100 * used / cap)
    return Usage(month=label, used_minutes=used, cap_minutes=cap, percent=percent, calls=int(calls),
                 allowed=cap is None or used < cap)


@router.get("/company/usage", response_model=Usage)
def company_usage(company: Company = Depends(get_current_company), db: Session = Depends(get_db)):
    return usage_for(db, company)


@router.get("/staff/usage", response_model=Usage)
def staff_usage(company: Company = Depends(get_staff_company), db: Session = Depends(get_db)):
    return usage_for(db, company)
