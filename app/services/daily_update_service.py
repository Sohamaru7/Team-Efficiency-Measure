from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.daily_update import DailyUpdate
from app.schemas.daily_update import DailyUpdateCreate, DailyUpdateUpdate


def create_daily_update(db: Session, data: DailyUpdateCreate) -> DailyUpdate:
    daily_update = DailyUpdate(**data.model_dump())
    db.add(daily_update)
    db.commit()
    db.refresh(daily_update)
    return daily_update


def get_daily_update(db: Session, daily_update_id: int) -> DailyUpdate | None:
    return db.get(DailyUpdate, daily_update_id)


def list_daily_updates(
    db: Session, skip: int = 0, limit: int = 100, user_id: int | None = None
) -> list[DailyUpdate]:
    stmt = select(DailyUpdate)
    if user_id is not None:
        stmt = stmt.where(DailyUpdate.user_id == user_id)
    stmt = stmt.order_by(DailyUpdate.date.desc(), DailyUpdate.id).offset(skip).limit(limit)
    return list(db.scalars(stmt))


def update_daily_update(db: Session, daily_update: DailyUpdate, data: DailyUpdateUpdate) -> DailyUpdate:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(daily_update, field, value)
    db.commit()
    db.refresh(daily_update)
    return daily_update


def delete_daily_update(db: Session, daily_update: DailyUpdate) -> None:
    db.delete(daily_update)
    db.commit()
