"""add agent action status result payload

Revision ID: 324ea72bf217
Revises: 7b691cd8bf07
Create Date: 2026-08-14 20:07:09.377606

Phase 7: the agent can now propose write actions that require manager approval. This adds
three columns to `agent_actions` — purely additive, no existing column is altered or dropped,
so the existing `approved` boolean (still written for backward compatibility) keeps working
unchanged for any code that only ever read it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '324ea72bf217'
down_revision: Union[str, None] = '7b691cd8bf07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

agent_action_status_enum = postgresql.ENUM(
    "pending", "auto_approved", "approved", "rejected", "failed", name="agent_action_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    agent_action_status_enum.create(bind, checkfirst=True)

    op.add_column(
        "agent_actions",
        sa.Column(
            "status", agent_action_status_enum, nullable=False, server_default="pending"
        ),
    )
    op.add_column("agent_actions", sa.Column("result", sa.Text(), nullable=True))
    op.add_column("agent_actions", sa.Column("payload", sa.Text(), nullable=True))
    op.create_index(op.f("ix_agent_actions_status"), "agent_actions", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_actions_status"), table_name="agent_actions")
    op.drop_column("agent_actions", "payload")
    op.drop_column("agent_actions", "result")
    op.drop_column("agent_actions", "status")

    bind = op.get_bind()
    agent_action_status_enum.drop(bind, checkfirst=True)
