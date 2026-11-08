"""staff logins, sessions and monthly usage cap

Revision ID: 0006
Revises: 0005

* companies.monthly_minutes_cap: most call minutes per month (NULL = no limit)
* staff_users: one row per real person (email + hashed password + role)
* staff_sessions: a login that expires; only a fingerprint of the token is stored
Both new tables get the same row-level security as every other company table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "jarvis_app"


def upgrade() -> None:
    op.add_column("companies", sa.Column("monthly_minutes_cap", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_company_cap", "companies", "monthly_minutes_cap IS NULL OR monthly_minutes_cap >= 0")

    op.create_table(
        "staff_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("password_hash", sa.String(length=300), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("failed_logins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'manager', 'agent')", name="ck_staff_user_role"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "email", name="uq_staff_user_email"),
    )
    op.create_index("ix_staff_users_company_id", "staff_users", ["company_id"])

    op.create_table(
        "staff_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["staff_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_staff_sessions_company_id", "staff_sessions", ["company_id"])
    op.create_index("ix_staff_sessions_user_id", "staff_sessions", ["user_id"])

    condition = "company_id = app_company_id() OR app_is_system()"
    for table in ("staff_users", "staff_sessions"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO {APP_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY company_isolation ON {table} USING ({condition}) WITH CHECK ({condition})")


def downgrade() -> None:
    for table in ("staff_sessions", "staff_users"):
        op.execute(f"DROP POLICY IF EXISTS company_isolation ON {table}")
        op.drop_table(table)
    op.drop_constraint("ck_company_cap", "companies", type_="check")
    op.drop_column("companies", "monthly_minutes_cap")
