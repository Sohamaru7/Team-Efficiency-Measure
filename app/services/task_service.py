from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import TaskStatus
from app.models.task import Task
from app.models.task_history import TaskHistory
from app.schemas.task import TaskCreate, TaskUpdate


def create_task(db: Session, data: TaskCreate) -> Task:
    task = Task(**data.model_dump())
    db.add(task)
    db.flush()
    db.add(TaskHistory(task_id=task.id, changed_by=None, old_status=None, new_status=task.status))
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: int) -> Task | None:
    return db.get(Task, task_id)


def list_tasks(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    project_id: int | None = None,
    assigned_to: int | None = None,
    status: TaskStatus | None = None,
) -> list[Task]:
    stmt = select(Task)
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if assigned_to is not None:
        stmt = stmt.where(Task.assigned_to == assigned_to)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    stmt = stmt.order_by(Task.id).offset(skip).limit(limit)
    return list(db.scalars(stmt))


def update_task(db: Session, task: Task, data: TaskUpdate) -> Task:
    payload = data.model_dump(exclude_unset=True)
    changed_by = payload.pop("changed_by", None)

    old_status = task.status
    for field, value in payload.items():
        setattr(task, field, value)
    db.flush()

    if "status" in payload and task.status != old_status:
        db.add(TaskHistory(task_id=task.id, changed_by=changed_by, old_status=old_status, new_status=task.status))

    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task: Task) -> None:
    db.delete(task)
    db.commit()
