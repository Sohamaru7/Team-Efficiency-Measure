from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import forbidden, get_current_user, require_admin, require_manager_or_admin
from app.database.session import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services import authz, user_service

router = APIRouter(prefix="/api/users", tags=["users"])


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)) -> User:
    """Admin-only: creating an account (with a password) is a system-management action."""
    try:
        return user_service.create_user(db, data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists"
        ) from exc


@router.get("", response_model=list[UserRead])
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    active: bool | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_admin),
) -> list[User]:
    """Manager/admin only. A manager's results are always restricted to their own team (same
    department) regardless of how large `limit` is — never "all employees" for a non-admin.
    """
    users = user_service.list_users(db, skip=skip, limit=limit, active=active)
    if authz.is_admin(current_user):
        return users
    return [u for u in users if authz.same_team(current_user, u) or u.id == current_user.id]


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> User:
    user = _get_user_or_404(db, user_id)
    if not authz.can_view_user(current_user, user):
        raise forbidden("You may only view your own profile or your team's.")
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int, data: UserUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> User:
    user = _get_user_or_404(db, user_id)
    changed_fields = set(data.model_dump(exclude_unset=True).keys())
    if data.password is not None:
        changed_fields.add("password")
    if not authz.can_modify_user(current_user, user, changed_fields):
        raise forbidden("You may only edit your own name/email — role, status, and password reset require an admin.")
    try:
        return user_service.update_user(db, user, data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists"
        ) from exc


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)) -> None:
    """Admin-only: deleting a user record is irreversible data deletion."""
    user = _get_user_or_404(db, user_id)
    user_service.delete_user(db, user)
