import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.models import Company, Customer
from app.security import get_current_company

router = APIRouter()


class CustomerCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=7, max_length=30)
    email: Optional[str] = Field(
        default=None, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )


class CustomerOut(BaseModel):
    id: int
    full_name: str
    phone: str


class CustomerResult(BaseModel):
    customer: CustomerOut
    already_existed: bool


def find_customer(db: Session, company_id: int, phone: str):
    return db.scalar(
        select(Customer).where(
            Customer.company_id == company_id, Customer.phone == phone
        )
    )


def to_out(customer: Customer) -> dict:
    return {"id": customer.id, "full_name": customer.full_name, "phone": customer.phone}


@router.post("/customers", response_model=CustomerResult)
def register_customer(
    payload: CustomerCreate,
    request: Request,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Registers a new customer in the key's company. Safe to repeat."""
    phone = re.sub(r"[\s\-()]", "", payload.phone)
    if not re.fullmatch(r"\+?\d{10,15}", phone):
        raise HTTPException(
            status_code=422,
            detail="The phone number must have 10 to 15 digits, for example +919000000001.",
        )

    # Already registered? Return them, change nothing.
    existing = find_customer(db, company.id, phone)
    if existing:
        return {"customer": to_out(existing), "already_existed": True}

    customer = Customer(
        company_id=company.id,
        full_name=payload.full_name.strip(),
        phone=phone,
        email=payload.email,
    )
    db.add(customer)
    try:
        db.flush()
        audit.record(db, request, company, "customer.register", "customer", customer.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = find_customer(db, company.id, phone)
        if existing:  # two identical requests raced each other
            return {"customer": to_out(existing), "already_existed": True}
        raise HTTPException(status_code=409, detail="Could not register the customer.")

    db.refresh(customer)
    return {"customer": to_out(customer), "already_existed": False}
