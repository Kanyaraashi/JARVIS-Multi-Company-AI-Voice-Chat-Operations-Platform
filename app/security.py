import hashlib

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, Company

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def get_current_company(
    api_key: str | None = Depends(api_key_header),
    db: Session = Depends(get_db),
) -> Company:
    """Finds the company that owns the API key. Every protected endpoint uses this."""
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    record = db.scalar(
        select(ApiKey).where(
            ApiKey.key_hash == hash_key(api_key),
            ApiKey.is_active.is_(True),
        )
    )
    if record is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    company = db.get(Company, record.company_id)
    if company is None or not company.is_active:
        raise HTTPException(status_code=403, detail="Company is not active")

    return company