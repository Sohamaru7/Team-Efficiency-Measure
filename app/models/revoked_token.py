from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class RevokedToken(Base):
    """One row per logged-out (or otherwise revoked) JWT access token, keyed by the token's own
    `jti` claim. `app.api.deps.get_current_user` checks this table on every authenticated
    request, so a logged-out token is rejected immediately rather than remaining valid until it
    naturally expires — real logout semantics on top of an otherwise-stateless JWT. Rows past
    `expires_at` are safe to prune (the token would be rejected as expired anyway); no automatic
    pruning job exists yet (see README Known Limitations).
    """

    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self) -> str:
        return f"<RevokedToken jti={self.jti!r}>"
