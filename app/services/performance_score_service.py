from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.performance_score import PerformanceScore


def get_performance_score(db: Session, performance_score_id: int) -> PerformanceScore | None:
    return db.get(PerformanceScore, performance_score_id)


def list_performance_scores(
    db: Session, skip: int = 0, limit: int = 100, user_id: int | None = None
) -> list[PerformanceScore]:
    stmt = select(PerformanceScore)
    if user_id is not None:
        stmt = stmt.where(PerformanceScore.user_id == user_id)
    stmt = stmt.order_by(PerformanceScore.period).offset(skip).limit(limit)
    return list(db.scalars(stmt))
