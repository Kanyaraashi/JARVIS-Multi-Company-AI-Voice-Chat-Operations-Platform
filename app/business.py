import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, Customer, Faq
from app.security import get_current_company

router = APIRouter()

STOP_WORDS = {
    "what", "are", "your", "the", "and", "you", "how", "when",
    "can", "for", "with", "does", "have", "about", "tell",
}


class CompanyInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    slug: str
    name: str
    agent_name: str
    greeting: str
    instructions: str
    default_language: str
    timezone: str


class FaqResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    question: str
    answer: str


class CustomerInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    phone: str
    email: Optional[str] = None


@router.get("/company/me", response_model=CompanyInfo)
def company_me(company: Company = Depends(get_current_company)):
    """Returns the settings of the company that owns the API key."""
    return company


@router.get("/faq/search", response_model=list[FaqResult])
def faq_search(
    q: str = Query(..., min_length=2, max_length=200),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Finds the best matching FAQs for this company only."""
    words = {
        w for w in re.findall(r"[a-z0-9]+", q.lower())
        if len(w) >= 3 and w not in STOP_WORDS
    }
    if not words:
        return []

    faqs = db.scalars(select(Faq).where(Faq.company_id == company.id)).all()

    scored = []
    for faq in faqs:
        text = f"{faq.question} {faq.answer}".lower()
        score = sum(1 for w in words if w in text)
        if score > 0:
            scored.append((score, faq))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [faq for _, faq in scored[:3]]


@router.get("/customers/lookup", response_model=CustomerInfo)
def customer_lookup(
    phone: str = Query(..., min_length=5, max_length=30),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Finds a customer by phone number, inside this company only."""
    cleaned = re.sub(r"[\s\-()]", "", phone)
    customer = db.scalar(
        select(Customer).where(
            Customer.company_id == company.id,
            Customer.phone == cleaned,
        )
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer