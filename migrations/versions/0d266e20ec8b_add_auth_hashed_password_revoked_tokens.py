"""add auth: hashed_password, revoked_tokens

Revision ID: 0d266e20ec8b
Revises: 986ba7efeae4
Create Date: 2026-08-15 12:00:00.000000

Production-readiness pass: real authentication. Adds `users.hashed_password` (nullable — a
user row without one simply cannot log in; existing/seeded/imported users are unaffected) and a
new standalone `revoked_tokens` table (logout support for otherwise-stateless JWTs). Additive
only — no existing column is altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0d266e20ec8b'
down_revision: Union[str, None] = '986ba7efeae4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("hashed_password", sa.String(length=255), nullable=True))

    op.create_table(
        "revoked_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("jti", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_revoked_tokens")),
        sa.UniqueConstraint("jti", name=op.f("uq_revoked_tokens_jti")),
    )
    op.create_index(op.f("ix_revoked_tokens_jti"), "revoked_tokens", ["jti"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_revoked_tokens_jti"), table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
    op.drop_column("users", "hashed_password")
