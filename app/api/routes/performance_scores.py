from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import forbidden, get_current_user
from app.database.session import get_db
from app.models.performance_score import PerformanceScore
from app.models.user import User
from app.schemas.performance_score import PerformanceScoreRead
from app.services import authz, performance_score_service

router = APIRouter(prefix="/api/performance-scores", tags=["performance-scores"])


def _can_view_scores_for(current_user: User, target_user: User | None) -> bool:
    if target_user is None:
        return False
    return authz.can_view_user(current_user, target_user)


@router.get("", response_model=list[PerformanceScoreRead])
def list_performance_scores(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PerformanceScore]:
    if authz.is_admin(current_user):
        pass
    elif not authz.is_manager(current_user):
        user_id = current_user.id
    scores = performance_score_service.list_performance_scores(db, skip=skip, limit=limit, user_id=user_id)
    if authz.is_admin(current_user):
        return scores
    return [s for s in scores if _can_view_scores_for(current_user, s.user)]


@router.get("/{performance_score_id}", response_model=PerformanceScoreRead)
def get_performance_score(
    performance_score_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> PerformanceScore:
    score = performance_score_service.get_performance_score(db, performance_score_id)
    if score is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Performance score not found")
    if not _can_view_scores_for(current_user, score.user):
        raise forbidden("You may only view your own performance scores or your team's.")
    return score
