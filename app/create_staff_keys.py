import secrets

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Company, StaffKey
from app.security import hash_key

with SessionLocal() as db:
    companies = db.scalars(select(Company).order_by(Company.id)).all()
    print(f"Found {len(companies)} companies")

    for company in companies:
        existing = db.scalar(
            select(StaffKey).where(
                StaffKey.company_id == company.id, StaffKey.is_active.is_(True)
            )
        )
        if existing:
            print(f"{company.slug}: already has an active staff key (cannot be shown again)")
            continue

        raw_key = "stf_" + secrets.token_urlsafe(32)
        db.add(StaffKey(company_id=company.id, key_hash=hash_key(raw_key)))
        print(f"{company.slug}: {raw_key}")

    db.commit()