"""create emails

Revision ID: f35cb212dc89
Revises: ebb203c4fb7f
Create Date: 2026-08-14 23:40:00.000000

Phase 9: email-based work context. This adds a new, standalone `emails` table (no changes to
any existing table) so emails can be associated with tasks/projects and their metadata used to
enrich delay classification. Direction/is_external are derived once at ingestion time from
address domains only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f35cb212dc89'
down_revision: Union[str, None] = 'ebb203c4fb7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

email_direction_enum = postgresql.ENUM("inbound", "outbound", name="email_direction", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    email_direction_enum.create(bind, checkfirst=True)

    op.create_table(
        "emails",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("message_id", sa.String(length=998), nullable=True),
        sa.Column("in_reply_to", sa.String(length=998), nullable=True),
        sa.Column("subject", sa.String(length=998), nullable=True),
        sa.Column("from_address", sa.String(length=320), nullable=False),
        sa.Column("to_addresses", sa.Text(), nullable=False),
        sa.Column("cc_addresses", sa.Text(), nullable=True),
        sa.Column("direction", email_direction_enum, nullable=False),
        sa.Column("is_external", sa.Boolean(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("linked_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("task_id IS NOT NULL OR project_id IS NOT NULL", name=op.f("ck_email_task_or_project")),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_emails_task_id_tasks"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_emails_project_id_projects"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["linked_by"], ["users.id"], name=op.f("fk_emails_linked_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_emails")),
        sa.UniqueConstraint("message_id", name=op.f("uq_emails_message_id")),
    )
    op.create_index(op.f("ix_emails_task_id"), "emails", ["task_id"], unique=False)
    op.create_index(op.f("ix_emails_project_id"), "emails", ["project_id"], unique=False)
    op.create_index(op.f("ix_emails_in_reply_to"), "emails", ["in_reply_to"], unique=False)
    op.create_index(op.f("ix_emails_direction"), "emails", ["direction"], unique=False)
    op.create_index(op.f("ix_emails_is_external"), "emails", ["is_external"], unique=False)
    op.create_index(op.f("ix_emails_sent_at"), "emails", ["sent_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_emails_sent_at"), table_name="emails")
    op.drop_index(op.f("ix_emails_is_external"), table_name="emails")
    op.drop_index(op.f("ix_emails_direction"), table_name="emails")
    op.drop_index(op.f("ix_emails_in_reply_to"), table_name="emails")
    op.drop_index(op.f("ix_emails_project_id"), table_name="emails")
    op.drop_index(op.f("ix_emails_task_id"), table_name="emails")
    op.drop_table("emails")

    bind = op.get_bind()
    email_direction_enum.drop(bind, checkfirst=True)
