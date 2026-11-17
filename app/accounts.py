"""Personal staff logins (Step 32).

POST /staff/login           company + email + password  ->  a token (stu_...) good for 12 hours
POST /staff/logout          ends that token
GET  /staff/me              who am I, what may I do
GET  /staff/users           list people                 (owner)
POST /staff/users           add a person                (owner)
PATCH /staff/users/{id}     change role, switch off, reset password (owner)

The token is sent in the same X-API-Key header as a staff key, so every staff screen works with both.
Roles: owner (everything), manager (settings, tickets, invoices), agent (tickets and appointments, no settings).
Passwords are stored as scrypt hashes. 5 wrong passwords lock that account for 15 minutes.
"""
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.audit import client_ip
from app.db import clear_context, get_db, use_system
from app.models import AuditLog, Company, StaffSession, StaffUser
from app.ratelimit import failure_limiter, reject
from app.security import get_staff_company, hash_key, require_role

router = APIRouter(prefix="/staff")

SESSION_HOURS = 12
MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 10
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(digest))
    except Exception:
        return False


_DUMMY = hash_password("not-a-real-password")      # so a wrong email takes as long as a wrong password


def password_problem(password: str) -> Optional[str]:
    if len(password) < MIN_PASSWORD:
        return f"The password must have at least {MIN_PASSWORD} characters."
    if password.lower() in {"password123", "1234567890", "qwertyuiop"} or len(set(password)) < 4:
        return "That password is too easy to guess."
    return None


class LoginIn(BaseModel):
    company: str = Field(min_length=1, max_length=50)
    email: str = Field(max_length=200, pattern=EMAIL)
    password: str = Field(min_length=1, max_length=200)


class LoginOut(BaseModel):
    token: str
    expires_at: datetime
    role: str
    full_name: str
    company: str


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    wait = failure_limiter.retry_after(ip)
    if wait:
        reject(wait)
    now = datetime.now(timezone.utc)
    email = payload.email.strip().lower()
    use_system(db)                                   # the company is not known until the login is checked
    try:
        company = db.scalar(select(Company).where(Company.slug == payload.company.strip().lower()))
        user = db.scalar(select(StaffUser).where(StaffUser.company_id == company.id, StaffUser.email == email)) if company else None
        if user is not None and user.locked_until and user.locked_until > now:
            raise HTTPException(status_code=429, detail="Too many wrong passwords. Try again in a few minutes.")
        good = check_password(payload.password, user.password_hash if user else _DUMMY)
        if not (user and good and user.is_active and company.is_active):
            failure_limiter.hit(ip)
            if user is not None and user.is_active:
                user.failed_logins += 1
                if user.failed_logins >= MAX_FAILED:
                    user.failed_logins = 0
                    user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                    db.add(AuditLog(company_id=company.id, actor_type="staff", actor_id=user.id, actor_label=email,
                                    action="staff_user.locked", target_type="staff_user", target_id=user.id, ip=ip))
                db.commit()
            raise HTTPException(status_code=401, detail="Invalid login")
        user.failed_logins, user.locked_until = 0, None
        token = "stu_" + secrets.token_urlsafe(32)
        expires = now + timedelta(hours=SESSION_HOURS)
        db.add(StaffSession(company_id=company.id, user_id=user.id, token_hash=hash_key(token), expires_at=expires))
        db.add(AuditLog(company_id=company.id, actor_type="staff", actor_id=user.id, actor_label=email,
                        action="staff_user.login", target_type="staff_user", target_id=user.id, ip=ip))
        out = LoginOut(token=token, expires_at=expires, role=user.role, full_name=user.full_name, company=company.slug)
        db.commit()
        return out
    finally:
        clear_context(db)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db), company: Company = Depends(get_staff_company)):
    actor = request.state.actor
    token = request.headers.get("x-api-key", "")
    if token.startswith("stu_"):
        session = db.scalar(select(StaffSession).where(StaffSession.token_hash == hash_key(token)))
        if session:
            session.revoked = True
            audit.record(db, request, company, "staff_user.logout", "staff_user", actor["id"])
            db.commit()
    return {"ok": True}


class Me(BaseModel):
    kind: str
    label: Optional[str]
    role: str
    company: str


@router.get("/me", response_model=Me)
def me(request: Request, company: Company = Depends(get_staff_company)):
    actor = request.state.actor
    return Me(kind=actor["via"], label=actor.get("label"), role=actor["role"], company=company.slug)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    locked: bool


def to_out(u: StaffUser) -> UserOut:
    locked = bool(u.locked_until and u.locked_until > datetime.now(timezone.utc))
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role, is_active=u.is_active, locked=locked)


class UserIn(BaseModel):
    email: str = Field(max_length=200, pattern=EMAIL)
    full_name: str = Field(min_length=2, max_length=200)
    role: Literal["owner", "manager", "agent"]
    password: str = Field(max_length=200)


class UserPatch(BaseModel):
    role: Optional[Literal["owner", "manager", "agent"]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, max_length=200)


@router.get("/users", response_model=list[UserOut])
def list_users(request: Request, company: Company = Depends(get_staff_company), db: Session = Depends(get_db)):
    require_role(request, "owner")
    rows = db.scalars(select(StaffUser).where(StaffUser.company_id == company.id).order_by(StaffUser.id))
    return [to_out(u) for u in rows]


@router.post("/users", response_model=UserOut, status_code=201)
def add_user(payload: UserIn, request: Request, company: Company = Depends(get_staff_company), db: Session = Depends(get_db)):
    require_role(request, "owner")
    problem = password_problem(payload.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    user = StaffUser(company_id=company.id, email=payload.email.strip().lower(), full_name=payload.full_name.strip(),
                     role=payload.role, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A person with this email already exists.")
    audit.record(db, request, company, "staff_user.create", "staff_user", user.id, {"email": user.email, "role": user.role})
    db.commit()
    return to_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def change_user(user_id: int, payload: UserPatch, request: Request,
                company: Company = Depends(get_staff_company), db: Session = Depends(get_db)):
    require_role(request, "owner")
    user = db.scalar(select(StaffUser).where(StaffUser.id == user_id, StaffUser.company_id == company.id))
    if user is None:
        raise HTTPException(status_code=404, detail="No such person.")
    changes = payload.model_dump(exclude_unset=True)
    if "password" in changes:
        problem = password_problem(changes["password"] or "")
        if problem:
            raise HTTPException(status_code=422, detail=problem)
    demoting = changes.get("role", user.role) != "owner" or changes.get("is_active", user.is_active) is False
    if user.role == "owner" and demoting:
        others = db.scalar(select(StaffUser.id).where(StaffUser.company_id == company.id, StaffUser.role == "owner",
                                                      StaffUser.is_active.is_(True), StaffUser.id != user.id).limit(1))
        if others is None:
            raise HTTPException(status_code=409, detail="The company needs at least one active owner.")
    details = {}
    if "role" in changes:
        details["role"] = [user.role, changes["role"]]; user.role = changes["role"]
    if "is_active" in changes:
        details["is_active"] = changes["is_active"]; user.is_active = changes["is_active"]
    if changes.get("password"):
        user.password_hash = hash_password(changes["password"]); user.failed_logins, user.locked_until = 0, None
        details["password"] = "reset"
    if "password" in changes or changes.get("is_active") is False:       # old logins stop working at once
        for s in db.scalars(select(StaffSession).where(StaffSession.user_id == user.id, StaffSession.revoked.is_(False))):
            s.revoked = True
    audit.record(db, request, company, "staff_user.update", "staff_user", user.id, details)
    db.commit()
    return to_out(user)
