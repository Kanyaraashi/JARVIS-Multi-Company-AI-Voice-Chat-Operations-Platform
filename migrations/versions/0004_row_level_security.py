"""row level security

Revision ID: 0004
Revises: 0003

Adds a second database user, jarvis_app, for the API to use at run time, and makes
PostgreSQL itself hide every row that does not belong to the current company.
Even a bug in the Python code can then not read or change another company's data.

The password for jarvis_app comes from JARVIS_APP_DB_PASSWORD (in .env).
An existing jarvis_app user is never changed, so running this twice is safe.
"""
import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "jarvis_app"

# Every table that holds one company's rows. A new table with a company_id column
# must be added here (the test suite fails if one is forgotten).
TENANT_TABLES = [
    "faqs", "customers", "support_tickets", "api_keys", "workflow_events",
    "appointments", "staff_keys", "ticket_updates", "invoices", "audit_log",
]


def upgrade() -> None:
    bind = op.get_bind()

    exists = bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": APP_ROLE}
    ).scalar()
    if not exists:
        password = os.environ.get("JARVIS_APP_DB_PASSWORD", "")
        if not re.fullmatch(r"[A-Za-z0-9_.\-]{16,}", password):
            raise RuntimeError(
                "JARVIS_APP_DB_PASSWORD is missing or not suitable. Put a line like "
                "JARVIS_APP_DB_PASSWORD=<at least 16 letters, digits, - _ .> in .env. "
                "Create one with: python -c \"import secrets; print(secrets.token_urlsafe(24))\""
            )
        op.execute(
            f"CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            f"NOBYPASSRLS PASSWORD '{password}'"
        )

    # What the API user may do: read, add and change rows. No deleting, no changing tables.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"REVOKE ALL ON alembic_version FROM {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )

    # Who is asking? The API sets these two values at the start of every transaction.
    op.execute(
        """
        CREATE FUNCTION app_company_id() RETURNS integer LANGUAGE sql STABLE AS
        $$ SELECT NULLIF(current_setting('app.company_id', true), '')::integer $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app_is_system() RETURNS boolean LANGUAGE sql STABLE AS
        $$ SELECT COALESCE(current_setting('app.system', true), 'off') = 'on' $$
        """
    )

    for table in TENANT_TABLES:
        _protect(table, "company_id")
    _protect("companies", "id")


def _protect(table: str, column: str) -> None:
    condition = f"{column} = app_company_id() OR app_is_system()"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY company_isolation ON {table} "
        f"USING ({condition}) WITH CHECK ({condition})"
    )


def downgrade() -> None:
    for table in TENANT_TABLES + ["companies"]:
        op.execute(f"DROP POLICY IF EXISTS company_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS app_is_system()")
    op.execute("DROP FUNCTION IF EXISTS app_company_id()")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {APP_ROLE}"
    )
    # The jarvis_app user itself is kept, because users belong to the whole server.
