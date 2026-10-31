from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Company, Customer, Invoice

IST = ZoneInfo("Asia/Kolkata")

# (phone, invoice number, issued at, amount in paise, status, description)
INVOICES = {
    "smile-dental": [
        ("+919000000001", "INV-1001", datetime(2026, 9, 12, 11, 0, tzinfo=IST), 50000, "paid", "Routine checkup"),
        ("+919000000001", "INV-1002", datetime(2026, 10, 20, 11, 0, tzinfo=IST), 120000, "unpaid", "Teeth cleaning"),
        ("+919000000002", "INV-1003", datetime(2026, 10, 5, 15, 30, tzinfo=IST), 250000, "paid", "Dental filling"),
        ("+917702895043", "INV-1004", datetime(2026, 10, 25, 10, 0, tzinfo=IST), 80000, "unpaid", "Consultation and X-ray"),
    ],
    "shopeasy": [
        ("+919000000003", "INV-2001", datetime(2026, 10, 18, 14, 0, tzinfo=IST), 199900, "paid", "Order 5521 - wireless headphones"),
    ],
}

with SessionLocal() as db:
    for slug, rows in INVOICES.items():
        company = db.scalar(select(Company).where(Company.slug == slug))
        if company is None:
            print(f"Skipping {slug}: company not found")
            continue
        for phone, number, issued, amount, status, description in rows:
            customer = db.scalar(
                select(Customer).where(
                    Customer.company_id == company.id, Customer.phone == phone
                )
            )
            if customer is None:
                print(f"Skipping {number}: no customer {phone} in {slug}")
                continue
            exists = db.scalar(
                select(Invoice.id).where(
                    Invoice.company_id == company.id, Invoice.invoice_number == number
                )
            )
            if exists:
                print(f"Skipping {number} (already exists)")
                continue
            db.add(
                Invoice(
                    company_id=company.id,
                    customer_id=customer.id,
                    invoice_number=number,
                    issued_at=issued,
                    amount_minor=amount,
                    currency="INR",
                    status=status,
                    description=description,
                )
            )
            print(f"Added {number} for {phone}")
    db.commit()