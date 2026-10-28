from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import Company, Customer, SupportTicket

with SessionLocal() as db:
    dental = db.scalar(select(Company).where(Company.slug == "smile-dental"))
    store = db.scalar(select(Company).where(Company.slug == "shopeasy"))
    dental_customer = db.scalar(
        select(Customer).where(Customer.company_id == dental.id)
    )

    # A ShopEasy ticket that points at a Smile Dental customer. This must fail.
    bad_ticket = SupportTicket(
        company_id=store.id,
        customer_id=dental_customer.id,
        subject="Cross-company attempt",
        description="This must be rejected by the database",
    )
    db.add(bad_ticket)
    try:
        db.commit()
        print("PROBLEM: the database accepted a cross-company ticket!")
    except IntegrityError:
        db.rollback()
        print("OK: the database rejected the cross-company ticket.")