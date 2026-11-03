"""call records

Revision ID: 0005
Revises: 0004

One row per finished phone or browser call: when, how long, how it ended, the
(masked) transcript, which tools ran, and how long the caller waited for answers.
The table is protected by row-level security like every other company table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "jarvis_app"


def upgrade() -> None:
    op.create_table(
        "call_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("room_name", sa.String(length=120), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("caller_phone", sa.String(length=30), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("transcript", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tools_used", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("latency_turns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("providers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound', 'web')", name="ck_call_direction"
        ),
        sa.CheckConstraint(
            "outcome IN ('completed', 'handoff', 'abandoned', 'failed')", name="ck_call_outcome"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["customers.company_id", "customers.id"],
            name="fk_call_customer_same_company",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "room_name", name="uq_call_company_room"),
    )
    op.create_index("ix_call_records_company_id", "call_records", ["company_id"])
    op.create_index("ix_call_company_started", "call_records", ["company_id", "started_at"])

    # Same protection as the other company tables (see migration 0004).
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON call_records TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE call_records_id_seq TO {APP_ROLE}")
    condition = "company_id = app_company_id() OR app_is_system()"
    op.execute("ALTER TABLE call_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE call_records FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY company_isolation ON call_records "
        f"USING ({condition}) WITH CHECK ({condition})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS company_isolation ON call_records")
    op.drop_index("ix_call_company_started", table_name="call_records")
    op.drop_index("ix_call_records_company_id", table_name="call_records")
    op.drop_table("call_records")
