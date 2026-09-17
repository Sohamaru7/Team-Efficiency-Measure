from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.import_history import ImportHistory


def list_history(db: Session, skip: int = 0, limit: int = 50) -> list[ImportHistory]:
    stmt = select(ImportHistory).order_by(ImportHistory.timestamp.desc()).offset(skip).limit(limit)
    return list(db.scalars(stmt))


def get_history(db: Session, history_id: int) -> ImportHistory | None:
    return db.get(ImportHistory, history_id)
