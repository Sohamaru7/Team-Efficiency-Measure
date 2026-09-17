from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User

_RANGE = "BETWEEN 0 AND 100"


class PerformanceScore(TimestampMixin, Base):
    __tablename__ = "performance_scores"
    __table_args__ = (
        UniqueConstraint("user_id", "period", name="uq_performance_score_user_period"),
        CheckConstraint(f"completion_score IS NULL OR completion_score {_RANGE}", name="ck_perf_completion_range"),
        CheckConstraint(f"timeliness_score IS NULL OR timeliness_score {_RANGE}", name="ck_perf_timeliness_range"),
        CheckConstraint(f"quality_score IS NULL OR quality_score {_RANGE}", name="ck_perf_quality_range"),
        CheckConstraint(
            f"time_efficiency_score IS NULL OR time_efficiency_score {_RANGE}",
            name="ck_perf_time_efficiency_range",
        ),
        CheckConstraint(f"workload_score IS NULL OR workload_score {_RANGE}", name="ck_perf_workload_range"),
        CheckConstraint(f"overall_score IS NULL OR overall_score {_RANGE}", name="ck_perf_overall_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    completion_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    timeliness_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    time_efficiency_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    workload_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    user: Mapped["User"] = relationship(back_populates="performance_scores")

    def __repr__(self) -> str:
        return f"<PerformanceScore id={self.id} user_id={self.user_id} period={self.period!r}>"
