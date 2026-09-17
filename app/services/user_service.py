from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


def create_user(db: Session, data: UserCreate) -> User:
    # `password` is excluded from model_dump() (Field(..., exclude=True) in the schema) so it
    # can never accidentally end up passed straight to User(**...) or logged via a dumped dict
    # — it's read directly off the validated model and hashed before the User row is built.
    user = User(**data.model_dump(), hashed_password=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def list_users(
    db: Session, skip: int = 0, limit: int = 100, active: bool | None = None
) -> list[User]:
    stmt = select(User)
    if active is not None:
        stmt = stmt.where(User.active == active)
    stmt = stmt.order_by(User.id).offset(skip).limit(limit)
    return list(db.scalars(stmt))


def update_user(db: Session, user: User, data: UserUpdate) -> User:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    if data.password is not None:
        # Admin-only reset path (see authz.can_modify_user / the route layer) — a self-service
        # password change goes through auth_service.set_password after verifying the current
        # password instead (POST /api/auth/change-password), never through this generic update.
        user.hashed_password = hash_password(data.password)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user: User) -> None:
    db.delete(user)
    db.commit()
