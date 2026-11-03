from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(
            "open_hour >= 0 AND close_hour <= 24 AND open_hour < close_hour",
            name="ck_company_hours",
        ),
        CheckConstraint(
            "slot_minutes IN (10, 15, 20, 30, 45, 60)", name="ck_company_slot_minutes"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    agent_name: Mapped[str] = mapped_column(String(100))
    greeting: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text)
    default_language: Mapped[str] = mapped_column(
        String(10), default="en", server_default="en"
    )
    timezone: Mapped[str] = mapped_column(
        String(50), default="Asia/Kolkata", server_default="Asia/Kolkata"
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    # Company settings (changed by staff, see /staff/company)
    staff_email: Mapped[Optional[str]] = mapped_column(String(200))
    open_hour: Mapped[int] = mapped_column(default=9, server_default="9")
    close_hour: Mapped[int] = mapped_column(default=18, server_default="18")
    slot_minutes: Mapped[int] = mapped_column(default=30, server_default="30")
    # Weekdays the company is closed: 0 = Monday ... 6 = Sunday
    closed_weekdays: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=lambda: [6], server_default=text("'{6}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Faq(Base):
    __tablename__ = "faqs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        # Needed so other tables can link to (company_id, id) together.
        UniqueConstraint("company_id", "id", name="uq_customers_company_id_id"),
        # The same phone number may exist in two companies, but not twice in one.
        UniqueConstraint("company_id", "phone", name="uq_customers_company_phone"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(30))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        # The customer must belong to the SAME company as the ticket.
        ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["customers.company_id", "customers.id"],
            name="fk_ticket_customer_same_company",
        ),
        # Retrying the same request cannot create a duplicate ticket.
        UniqueConstraint(
            "company_id", "idempotency_key", name="uq_ticket_company_idempotency"
        ),
        CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'closed')",
            name="ck_ticket_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_ticket_priority",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    customer_id: Mapped[Optional[int]]
    subject: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default="open", server_default="open"
    )
    priority: Mapped[str] = mapped_column(
        String(20), default="normal", server_default="normal"
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(
        String(100), default="default", server_default="default"
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    ticket_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("support_tickets.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        # The customer must belong to the SAME company as the appointment.
        ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["customers.company_id", "customers.id"],
            name="fk_appointment_customer_same_company",
        ),
        # A retried request cannot create a second appointment.
        UniqueConstraint(
            "company_id", "idempotency_key", name="uq_appointment_company_idempotency"
        ),
        # Two booked appointments cannot share the same slot in one company.
        Index(
            "uq_appointment_company_slot",
            "company_id",
            "starts_at",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
        CheckConstraint(
            "status IN ('booked', 'cancelled', 'completed')",
            name="ck_appointment_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    customer_id: Mapped[int]
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[Optional[str]] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(
        String(20), default="booked", server_default="booked"
    )
    idempotency_key: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StaffKey(Base):
    __tablename__ = "staff_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(
        String(100), default="staff", server_default="staff"
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TicketUpdate(Base):
    __tablename__ = "ticket_updates"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id"), index=True)
    old_status: Mapped[str] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20))
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        # The customer must belong to the SAME company as the invoice.
        ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["customers.company_id", "customers.id"],
            name="fk_invoice_customer_same_company",
        ),
        UniqueConstraint("company_id", "invoice_number", name="uq_invoice_company_number"),
        CheckConstraint("status IN ('paid', 'unpaid')", name="ck_invoice_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    customer_id: Mapped[int]
    invoice_number: Mapped[str] = mapped_column(String(40))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount_minor: Mapped[int]  # paise, so 50000 means INR 500.00
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR")
    status: Mapped[str] = mapped_column(
        String(10), default="unpaid", server_default="unpaid"
    )
    description: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_company_created", "company_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    actor_type: Mapped[Optional[str]] = mapped_column(String(10))  # "ai" or "staff"
    actor_id: Mapped[Optional[int]]  # the id of the key that was used
    actor_label: Mapped[Optional[str]] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[Optional[str]] = mapped_column(String(30))
    target_id: Mapped[Optional[int]]
    details: Mapped[Optional[dict]] = mapped_column(JSONB)
    ip: Mapped[Optional[str]] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CallRecord(Base):
    __tablename__ = "call_records"
    __table_args__ = (
        # The customer must belong to the SAME company as the call.
        ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["customers.company_id", "customers.id"],
            name="fk_call_customer_same_company",
        ),
        # Sending the same finished call twice cannot create a second record.
        UniqueConstraint("company_id", "room_name", name="uq_call_company_room"),
        CheckConstraint(
            "direction IN ('inbound', 'outbound', 'web')", name="ck_call_direction"
        ),
        CheckConstraint(
            "outcome IN ('completed', 'handoff', 'abandoned', 'failed')",
            name="ck_call_outcome",
        ),
        Index("ix_call_company_started", "company_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    room_name: Mapped[str] = mapped_column(String(120))
    direction: Mapped[str] = mapped_column(String(10))
    caller_phone: Mapped[Optional[str]] = mapped_column(String(30))
    customer_id: Mapped[Optional[int]]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int]
    outcome: Mapped[str] = mapped_column(String(10))
    turn_count: Mapped[int]  # how many times the caller spoke
    transcript: Mapped[list] = mapped_column(JSONB)  # personal data already masked
    tools_used: Mapped[list] = mapped_column(JSONB)  # tool name and ok, never the details
    latency_turns: Mapped[list] = mapped_column(JSONB)
    providers: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
