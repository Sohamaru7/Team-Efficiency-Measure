from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import forbidden, get_current_user
from app.database.session import get_db
from app.models.daily_update import DailyUpdate
from app.models.user import User
from app.schemas.daily_update import DailyUpdateCreate, DailyUpdateRead, DailyUpdateUpdate
from app.services import authz, daily_update_service

router = APIRouter(prefix="/api/daily-updates", tags=["daily-updates"])


def _get_daily_update_or_404(db: Session, daily_update_id: int) -> DailyUpdate:
    obj = daily_update_service.get_daily_update(db, daily_update_id)
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily update not found")
    return obj


@router.post("", response_model=DailyUpdateRead, status_code=status.HTTP_201_CREATED)
def create_daily_update(
    data: DailyUpdateCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> DailyUpdate:
    if not authz.can_create_daily_update_for(current_user, data.user_id):
        raise forbidden("You may only submit your own daily update.")
    try:
        return daily_update_service.create_daily_update(db, data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A daily update for this user and date already exists, or user_id is invalid",
        ) from exc


@router.get("", response_model=list[DailyUpdateRead])
def list_daily_updates(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DailyUpdate]:
    if authz.is_admin(current_user):
        pass
    elif not authz.is_manager(current_user):
        user_id = current_user.id
    updates = daily_update_service.list_daily_updates(db, skip=skip, limit=limit, user_id=user_id)
    if authz.is_admin(current_user):
        return updates
    return [u for u in updates if authz.can_view_daily_update(current_user, u)]


@router.get("/{daily_update_id}", response_model=DailyUpdateRead)
def get_daily_update(
    daily_update_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> DailyUpdate:
    obj = _get_daily_update_or_404(db, daily_update_id)
    if not authz.can_view_daily_update(current_user, obj):
        raise forbidden("You may only view your own daily updates or your team's.")
    return obj


@router.patch("/{daily_update_id}", response_model=DailyUpdateRead)
def update_daily_update(
    daily_update_id: int,
    data: DailyUpdateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailyUpdate:
    obj = _get_daily_update_or_404(db, daily_update_id)
    if not authz.can_modify_daily_update(current_user, obj):
        raise forbidden("You may only edit your own daily update.")
    try:
        return daily_update_service.update_daily_update(db, obj, data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A daily update for this user and date already exists"
        ) from exc


@router.delete("/{daily_update_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_daily_update(
    daily_update_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    obj = _get_daily_update_or_404(db, daily_update_id)
    if not authz.can_modify_daily_update(current_user, obj):
        raise forbidden("You may only delete your own daily update.")
    daily_update_service.delete_daily_update(db, obj)
