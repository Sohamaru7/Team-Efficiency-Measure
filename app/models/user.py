from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.daily_update import DailyUpdate
    from app.models.performance_score import PerformanceScore
    from app.models.project import Project
    from app.models.task import Task
    from app.models.task_history import TaskHistory


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.EMPLOYEE,
        server_default=UserRole.EMPLOYEE.value,
    )
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    hashed_password: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="bcrypt hash (see app.core.security) — never a plaintext password. Nullable so a "
        "user record can exist without login capability (e.g. seeded/imported data); such a "
        "user simply cannot authenticate until an admin sets a password. Never serialized in "
        "any response schema (see app.schemas.user.UserRead).",
    )

    managed_projects: Mapped[list["Project"]] = relationship(
        back_populates="manager", foreign_keys="Project.manager_id"
    )
    assigned_tasks: Mapped[list["Task"]] = relationship(
        back_populates="assignee", foreign_keys="Task.assigned_to"
    )
    daily_updates: Mapped[list["DailyUpdate"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    performance_scores: Mapped[list["PerformanceScore"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    task_history_entries: Mapped[list["TaskHistory"]] = relationship(
        back_populates="changed_by_user", foreign_keys="TaskHistory.changed_by"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
