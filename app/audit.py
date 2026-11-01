"""Writes the audit trail: who changed what, and when."""
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, Company


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


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
