from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ImportHistory(Base):
    """One row per attempted Excel/CSV import (Phase 8) — preview runs are not logged here,
    only commits, so this table is a record of imports that actually happened (or were
    actually attempted and failed), not of every file a manager looked at.
    """

    __tablename__ = "import_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    imported_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    rows_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    errors: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="JSON-encoded list of per-row (or file-level) error details for every row that "
        "was not accepted, so a manager can see exactly why without re-uploading the file.",
    )

    def __repr__(self) -> str:
        return f"<ImportHistory id={self.id} filename={self.filename!r} accepted={self.rows_accepted} rejected={self.rows_rejected}>"
