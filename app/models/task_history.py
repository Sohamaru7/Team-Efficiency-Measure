from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import TaskStatus

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class TaskHistory(Base):
    __tablename__ = "task_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    old_status: Mapped[TaskStatus | None] = mapped_column(
        Enum(TaskStatus, name="task_status"), nullable=True
    )
    new_status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    task: Mapped["Task"] = relationship(back_populates="history")
    changed_by_user: Mapped["User | None"] = relationship(
        back_populates="task_history_entries", foreign_keys=[changed_by]
    )

    def __repr__(self) -> str:
        return f"<TaskHistory id={self.id} task_id={self.task_id} new_status={self.new_status}>"
