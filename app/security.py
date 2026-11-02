import hashlib
import logging

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import client_ip
from app.db import clear_context, get_db, use_company, use_system
from app.models import ApiKey, Company, StaffKey
from app.ratelimit import failure_limiter, reject, request_limiter

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
log = logging.getLogger("app.security")


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _company_for_key(model, kind: str, api_key: str | None, db: Session, request: Request) -> Company:
    ip = client_ip(request)

    # Someone guessing keys gets blocked for a while.
    wait = failure_limiter.retry_after(ip)
    if wait:
        reject(wait)

    if not api_key:
        failure_limiter.hit(ip)
        raise HTTPException(status_code=401, detail="Missing API key")

    key_hash = hash_key(api_key)
    use_system(db)  # the company is not known yet, so the key itself must be looked up
    try:
        record = db.scalar(
            select(model).where(model.key_hash == key_hash, model.is_active.is_(True))
        )
        company = db.get(Company, record.company_id) if record else None
    finally:
        clear_context(db)  # never stay in system mode, whatever happens above

    if record is None:
        failure_limiter.hit(ip)
        log.warning("Rejected %s key from %s", kind, ip)
        raise HTTPException(status_code=401, detail="Invalid API key")

    if company is None or not company.is_active:
        raise HTTPException(status_code=403, detail="Company is not active")

    # From here on the database only shows this company's rows.
    use_company(db, company.id)

    # A valid key may still not send unlimited requests.
    bucket = f"{kind}:{key_hash}"
    wait = request_limiter.retry_after(bucket)
    if wait:
        reject(wait)
    request_limiter.hit(bucket)

    request.state.actor = {"type": kind, "id": record.id, "label": record.label}
    return company


def get_current_company(
    request: Request,
    api_key: str | None = Depends(api_key_header),
    db: Session = Depends(get_db),
) -> Company:
    """For the AI agent's key. Staff keys are not accepted here."""
    return _company_for_key(ApiKey, "ai", api_key, db, request)


def get_staff_company(
    request: Request,
    api_key: str | None = Depends(api_key_header),
    db: Session = Depends(get_db),
) -> Company:
    """For human staff keys only. The AI agent's key is not accepted here."""
    return _company_for_key(StaffKey, "staff", api_key, db, request)
