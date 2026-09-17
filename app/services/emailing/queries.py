from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email import Email


def get_email(db: Session, email_id: int) -> Email | None:
    return db.get(Email, email_id)


def list_emails(
    db: Session,
    *,
    task_id: int | None = None,
    project_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Email]:
    stmt = select(Email)
    if task_id is not None:
        stmt = stmt.where(Email.task_id == task_id)
    if project_id is not None:
        stmt = stmt.where(Email.project_id == project_id)
    stmt = stmt.order_by(Email.sent_at.desc()).offset(skip).limit(limit)
    return list(db.scalars(stmt))


def list_emails_for_task(db: Session, task_id: int) -> list[Email]:
    stmt = select(Email).where(Email.task_id == task_id).order_by(Email.sent_at)
    return list(db.scalars(stmt))
