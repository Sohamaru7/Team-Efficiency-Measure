from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin
from app.models.enums import TaskPriority, TaskStatus

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.task_history import TaskHistory
    from app.models.user import User


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("estimated_hours IS NULL OR estimated_hours >= 0", name="ck_task_estimated_hours_nonneg"),
        CheckConstraint("actual_hours IS NULL OR actual_hours >= 0", name="ck_task_actual_hours_nonneg"),
        CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
            name="ck_task_quality_score_range",
        ),
        CheckConstraint(
            "deadline IS NULL OR start_date IS NULL OR deadline >= start_date",
            name="ck_task_deadline_after_start",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, name="task_priority"),
        nullable=False,
        default=TaskPriority.MEDIUM,
        server_default=TaskPriority.MEDIUM.value,
        index=True,
    )
    estimated_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    actual_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    start_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    deadline: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    completed_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"),
        nullable=False,
        default=TaskStatus.NOT_STARTED,
        server_default=TaskStatus.NOT_STARTED.value,
        index=True,
    )
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    delay_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="tasks")
    assignee: Mapped["User | None"] = relationship(
        back_populates="assigned_tasks", foreign_keys=[assigned_to]
    )
    history: Mapped[list["TaskHistory"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskHistory.timestamp"
    )

    def __repr__(self) -> str:
        return f"<Task id={self.id} title={self.title!r}>"
