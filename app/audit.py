"""Writes the audit trail: who changed what, and when."""
import ipaddress
import os
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, Company


def client_ip(request: Request) -> str:
    """The caller's address, for rate limits and the audit log.

    Behind a proxy (Caddy) every request seems to come from the proxy itself, so ONE wrong key would
    lock out EVERYONE. Set TRUSTED_PROXY_COUNT=1 when exactly one proxy of yours sits in front. We then
    read X-Forwarded-For from the RIGHT, because the left side can be faked by the caller.
    With the default 0 the header is ignored completely."""
    peer = request.client.host if request.client else "unknown"
    try:
        trusted = int(os.getenv("TRUSTED_PROXY_COUNT", "0"))
    except ValueError:
        trusted = 0
    if trusted <= 0:
        return peer
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if len(parts) < trusted:
        return peer
    candidate = parts[-trusted]
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return peer
    return candidate


def record(
    db: Session,
    request: Request,
    company: Company,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    details: Optional[dict] = None,
) -> None:
    """Adds an audit row to the current transaction. The caller's commit saves it
    together with the change itself, so there is never a change without its record."""
    actor = getattr(request.state, "actor", None) or {}
    db.add(
        AuditLog(
            company_id=company.id,
            actor_type=actor.get("type"),
            actor_id=actor.get("id"),
            actor_label=actor.get("label"),
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
            ip=client_ip(request),
        )
    )
