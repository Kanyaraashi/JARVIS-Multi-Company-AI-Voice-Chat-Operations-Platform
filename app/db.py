import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in .env")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    """All database table classes will inherit from this."""


# ---------- row-level security context ----------
# The database itself hides every row that does not belong to the "current company".
# These helpers tell the database who that is. With no context a session sees NOTHING.
#   use_company(db, 3)  ->  only company 3's rows are visible and writable
#   use_system(db)      ->  all rows (key lookup, background jobs that serve every company)

_SET_CONTEXT = text(
    "SELECT set_config('app.company_id', :company, true), set_config('app.system', :system, true)"
)


def _context_params(info: dict) -> dict:
    return {
        "company": str(info.get("company_id") or ""),
        "system": "on" if info.get("system") else "off",
    }


@event.listens_for(Session, "after_begin")
def _apply_context(session, transaction, connection):
    """Every new transaction starts by telling PostgreSQL which company it works for.
    The setting is local to the transaction, so a pooled connection never leaks it."""
    if connection.dialect.name == "postgresql":
        connection.execute(_SET_CONTEXT, _context_params(session.info))


def _switch(db: Session, **info) -> None:
    db.info.pop("company_id", None)
    db.info.pop("system", None)
    db.info.update(info)
    if db.in_transaction():  # a transaction is already open: change it right now
        db.execute(_SET_CONTEXT, _context_params(db.info))


def use_company(db: Session, company_id: int) -> None:
    _switch(db, company_id=company_id)


def use_system(db: Session) -> None:
    _switch(db, system=True)


def clear_context(db: Session) -> None:
    """Back to the safe default: the session sees nothing."""
    _switch(db)


def get_db():
    """Gives one database session per request, then closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
