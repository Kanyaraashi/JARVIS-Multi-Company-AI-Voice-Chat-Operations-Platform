import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.events import send_event
from app.models import Company, Customer, Invoice, WorkflowEvent
from app.privacy import mask_email
from app.security import get_current_company

router = APIRouter()

COOLDOWN_MINUTES = 10


class InvoiceRequest(BaseModel):
    customer_phone: str = Field(min_length=5, max_length=30)


class InvoiceRequestResult(BaseModel):
    requested: bool
    already_requested: bool
    email_hint: str


@router.post("/invoices/email-request", response_model=InvoiceRequestResult)
def email_latest_invoice(
    payload: InvoiceRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    """Emails the customer's latest invoice to the address on file.
    The response never contains invoice details, only a masked email address."""
    cleaned = re.sub(r"[\s\-()]", "", payload.customer_phone)
    customer = db.scalar(
        select(Customer).where(
            Customer.company_id == company.id, Customer.phone == cleaned
        )
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not customer.email:
        raise HTTPException(
            status_code=422,
            detail="There is no email address on file for this customer, so the invoice cannot be sent by email.",
        )

    invoice = db.scalar(
        select(Invoice)
        .where(Invoice.company_id == company.id, Invoice.customer_id == customer.id)
        .order_by(Invoice.issued_at.desc(), Invoice.id.desc())
        .limit(1)
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="No invoices found for this customer")

    hint = mask_email(customer.email)

    # Asked again within a few minutes? Do not send another email.
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=COOLDOWN_MINUTES)
    recent = db.scalar(
        select(WorkflowEvent.id)
        .where(
            WorkflowEvent.company_id == company.id,
            WorkflowEvent.event_type == "invoice_requested",
            WorkflowEvent.created_at > cutoff,
            WorkflowEvent.payload["invoice"]["number"].astext == invoice.invoice_number,
        )
        .limit(1)
    )
    if recent:
        return {"requested": True, "already_requested": True, "email_hint": hint}

    issued = invoice.issued_at.astimezone(ZoneInfo(company.timezone))
    event = WorkflowEvent(
        company_id=company.id,
        event_type="invoice_requested",
        payload={
            "company": {
                "slug": company.slug,
                "name": company.name,
                "agent_name": company.agent_name,
            },
            "customer": {"name": customer.full_name, "email": customer.email},
            "invoice": {
                "number": invoice.invoice_number,
                "date": issued.strftime("%d %B %Y"),
                "description": invoice.description,
                "amount": f"{invoice.currency} {invoice.amount_minor / 100:,.2f}",
                "status": invoice.status.upper(),
            },
        },
    )
    db.add(event)
    audit.record(
        db, request, company, "invoice.email_request", "customer", customer.id,
        {"invoice_number": invoice.invoice_number},
    )
    db.commit()

    background_tasks.add_task(send_event, event.id)
    return {"requested": True, "already_requested": False, "email_hint": hint}
