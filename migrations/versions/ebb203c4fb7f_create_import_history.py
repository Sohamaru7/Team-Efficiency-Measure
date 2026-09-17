"""create import_history

Revision ID: ebb203c4fb7f
Revises: 324ea72bf217
Create Date: 2026-08-14 22:30:00.000000

Phase 8: Excel/CSV data import/export. This adds a new, standalone `import_history` table
(no changes to any existing table) recording every attempted import commit — preview runs are
never logged, only actual commits (including ones that failed at the file level) — so managers
can audit exactly what was imported, when, by whom, and what was rejected and why.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ebb203c4fb7f'
down_revision: Union[str, None] = '324ea72bf217'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("imported_by", sa.Integer(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("rows_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_accepted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["imported_by"], ["users.id"], name=op.f("fk_import_history_imported_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_history")),
    )
    op.create_index(op.f("ix_import_history_imported_by"), "import_history", ["imported_by"], unique=False)
    op.create_index(op.f("ix_import_history_timestamp"), "import_history", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_import_history_timestamp"), table_name="import_history")
    op.drop_index(op.f("ix_import_history_imported_by"), table_name="import_history")
    op.drop_table("import_history")
