from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Company(Base):
    __tablename__ = "companies"

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