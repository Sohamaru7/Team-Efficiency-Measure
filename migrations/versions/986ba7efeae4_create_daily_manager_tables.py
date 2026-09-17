"""create daily manager tables

Revision ID: 986ba7efeae4
Revises: f35cb212dc89
Create Date: 2026-08-15 09:00:00.000000

Phase 10: Autonomous Daily Manager. Adds two new, standalone tables (no changes to any
existing table): `daily_manager_reports` (one row per autonomous run, the audit record and the
generated report) and `daily_manager_issue_state` (tracks ongoing issues across days so the
pipeline can tell new/escalated/resolved apart from "same as yesterday").
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '986ba7efeae4'
down_revision: Union[str, None] = 'f35cb212dc89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_manager_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("team_efficiency", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("action_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actions_taken_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_manager_reports")),
        sa.UniqueConstraint("run_date", name=op.f("uq_daily_manager_reports_run_date")),
    )
    op.create_index(op.f("ix_daily_manager_reports_run_date"), "daily_manager_reports", ["run_date"], unique=False)

    op.create_table(
        "daily_manager_issue_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("issue_type", sa.String(length=50), nullable=False),
        sa.Column("target_key", sa.String(length=120), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("first_detected_at", sa.Date(), nullable=False),
        sa.Column("last_seen_at", sa.Date(), nullable=False),
        sa.Column("last_reported_severity", sa.String(length=20), nullable=False),
        sa.Column("resolved_at", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_manager_issue_state")),
        sa.UniqueConstraint("issue_type", "target_key", name=op.f("uq_daily_manager_issue_state_type_key")),
    )
    op.create_index(op.f("ix_daily_manager_issue_state_issue_type"), "daily_manager_issue_state", ["issue_type"], unique=False)
    op.create_index(op.f("ix_daily_manager_issue_state_target_key"), "daily_manager_issue_state", ["target_key"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_daily_manager_issue_state_target_key"), table_name="daily_manager_issue_state")
    op.drop_index(op.f("ix_daily_manager_issue_state_issue_type"), table_name="daily_manager_issue_state")
    op.drop_table("daily_manager_issue_state")

    op.drop_index(op.f("ix_daily_manager_reports_run_date"), table_name="daily_manager_reports")
    op.drop_table("daily_manager_reports")
