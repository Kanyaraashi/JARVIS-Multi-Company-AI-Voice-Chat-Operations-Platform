import hashlib
import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import client_ip
from app.db import clear_context, get_db, use_company, use_system
from app.models import ApiKey, Company, StaffKey, StaffSession, StaffUser
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

    # A staff KEY belongs to the whole company, so it has the owner's rights.
    request.state.actor = {"type": kind, "id": record.id, "label": record.label, "role": "owner", "via": "key"}
    return company


def _company_for_session(token: str, db: Session, request: Request) -> Company:
    """A person who logged in with email and password (token starts with stu_)."""
    ip = client_ip(request)
    wait = failure_limiter.retry_after(ip)
    if wait:
        reject(wait)
    token_hash = hash_key(token)
    use_system(db)
    try:
        session = db.scalar(select(StaffSession).where(StaffSession.token_hash == token_hash))
        valid = (session is not None and not session.revoked
                 and session.expires_at > datetime.now(timezone.utc))
        user = db.get(StaffUser, session.user_id) if valid else None
        company = db.get(Company, session.company_id) if user else None
        email = user.email if user else None
        role = user.role if user else None
        user_ok = bool(user and user.is_active)
    finally:
        clear_context(db)
    if not (valid and user_ok):
        failure_limiter.hit(ip)
        raise HTTPException(status_code=401, detail="Invalid API key")
    if company is None or not company.is_active:
        raise HTTPException(status_code=403, detail="Company is not active")
    use_company(db, company.id)
    bucket = f"user:{token_hash}"
    wait = request_limiter.retry_after(bucket)
    if wait:
        reject(wait)
    request_limiter.hit(bucket)
    request.state.actor = {"type": "staff", "id": session.user_id, "label": email, "role": role, "via": "login"}
    return company


def require_role(request: Request, *roles: str) -> None:
    """403 unless the person's role is one of these. Staff keys count as owner."""
    actor = getattr(request.state, "actor", None) or {}
    if actor.get("role") not in roles:
        raise HTTPException(status_code=403, detail="Your role is not allowed to do this.")


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
    """For humans: a staff key (stf_) or a personal login token (stu_). The AI key is not accepted."""
    if api_key and api_key.startswith("stu_"):
        return _company_for_session(api_key, db, request)
    return _company_for_key(StaffKey, "staff", api_key, db, request)
