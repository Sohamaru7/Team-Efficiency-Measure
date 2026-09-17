from __future__ import annotations

from datetime import date as date_type
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class DailyUpdate(TimestampMixin, Base):
    __tablename__ = "daily_updates"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_daily_update_user_date"),
        CheckConstraint("tasks_completed >= 0", name="ck_daily_update_tasks_completed_nonneg"),
        CheckConstraint("tasks_pending >= 0", name="ck_daily_update_tasks_pending_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    tasks_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tasks_pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    blockers: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="daily_updates")

    def __repr__(self) -> str:
        return f"<DailyUpdate id={self.id} user_id={self.user_id} date={self.date}>"
