import secrets

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ApiKey, Company
from app.security import hash_key

with SessionLocal() as db:
    companies = db.scalars(select(Company).order_by(Company.id)).all()
    for company in companies:
        existing = db.scalar(
            select(ApiKey).where(
                ApiKey.company_id == company.id, ApiKey.is_active.is_(True)
            )
        )
        if existing:
            print(f"{company.slug}: already has an active key (cannot be shown again)")
            continue

        raw_key = "jrv_" + secrets.token_urlsafe(32)
        db.add(ApiKey(company_id=company.id, key_hash=hash_key(raw_key), label="default"))
        print(f"{company.slug}: {raw_key}")

    db.commit()