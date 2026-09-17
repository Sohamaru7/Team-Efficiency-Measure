from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import forbidden, get_current_user
from app.database.session import get_db
from app.models.enums import TaskStatus
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services import authz, task_service

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _get_task_or_404(db: Session, task_id: int) -> Task:
    task = task_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(data: TaskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Task:
    """Employees may only create a task assigned to themselves (Phase 3's self-service "Add
    Task"); managers/admins may create a task for anyone.
    """
    if not authz.can_create_task_for(current_user, data.assigned_to):
        raise forbidden("You may only create tasks assigned to yourself.")
    try:
        return task_service.create_task(db, data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reference (e.g. project_id or assigned_to does not exist)",
        ) from exc


@router.get("", response_model=list[TaskRead])
def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    project_id: int | None = None,
    assigned_to: int | None = None,
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Task]:
    """Employees always see only their own tasks (the `assigned_to` filter is force-set to
    themselves, regardless of what was requested); managers see their team's + their managed
    projects'; admins see everything.
    """
    if authz.is_admin(current_user):
        pass
    elif not authz.is_manager(current_user):
        assigned_to = current_user.id
    tasks = task_service.list_tasks(
        db, skip=skip, limit=limit, project_id=project_id, assigned_to=assigned_to, status=status_filter
    )
    if authz.is_admin(current_user):
        return tasks
    return [t for t in tasks if authz.can_view_task(current_user, t)]


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Task:
    task = _get_task_or_404(db, task_id)
    if not authz.can_view_task(current_user, task):
        raise forbidden("You may only view your own tasks or your team's.")
    return task


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int, data: TaskUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Task:
    task = _get_task_or_404(db, task_id)
    if not authz.can_modify_task(current_user, task):
        raise forbidden("You may only update your own tasks or your team's.")
    # changed_by is always the real authenticated user, never a client-supplied id — closes the
    # "caller-supplied identity, trusted at face value" gap every earlier phase's README flagged.
    data = data.model_copy(update={"changed_by": current_user.id})
    try:
        return task_service.update_task(db, task, data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reference (e.g. project_id or assigned_to does not exist)",
        ) from exc


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> None:
    """Deletion is narrower than view/update: an employee may not delete their own task, only a
    manager (of their team/project) or admin can (see app.services.authz.can_delete_task).
    """
    task = _get_task_or_404(db, task_id)
    if not authz.can_delete_task(current_user, task):
        raise forbidden("Only a manager or admin may delete a task.")
    task_service.delete_task(db, task)
