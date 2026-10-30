import hashlib

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, Company, StaffKey

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _company_for_key(model, api_key: str | None, db: Session) -> Company:
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    record = db.scalar(
        select(model).where(
            model.key_hash == hash_key(api_key),
            model.is_active.is_(True),
        )
    )
    if record is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    company = db.get(Company, record.company_id)
    if company is None or not company.is_active:
        raise HTTPException(status_code=403, detail="Company is not active")
    return company


def get_current_company(
    api_key: str | None = Depends(api_key_header),
    db: Session = Depends(get_db),
) -> Company:
    """For the AI agent's key. Staff keys are not accepted here."""
    return _company_for_key(ApiKey, api_key, db)


def get_staff_company(
    api_key: str | None = Depends(api_key_header),
    db: Session = Depends(get_db),
) -> Company:
    """For human staff keys only. The AI agent's key is not accepted here."""
    return _company_for_key(StaffKey, api_key, db)