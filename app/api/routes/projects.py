from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import forbidden, get_current_user, require_manager_or_admin
from app.database.session import get_db
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services import authz, project_service, task_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_project_or_404(db: Session, project_id: int) -> Project:
    project = project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _employee_has_task_in(db: Session, project_id: int, user_id: int) -> bool:
    return len(task_service.list_tasks(db, skip=0, limit=1, project_id=project_id, assigned_to=user_id)) > 0


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    data: ProjectCreate, db: Session = Depends(get_db), current_user: User = Depends(require_manager_or_admin)
) -> Project:
    try:
        return project_service.create_project(db, data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reference (e.g. manager_id does not exist)"
        ) from exc


@router.get("", response_model=list[ProjectRead])
def list_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status_filter: ProjectStatus | None = Query(default=None, alias="status"),
    manager_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_admin),
) -> list[Project]:
    """Manager/admin only — an employee needing context on a specific project they have a task
    in should use `GET /api/projects/{id}` instead of listing all projects.
    """
    return project_service.list_projects(db, skip=skip, limit=limit, status=status_filter, manager_id=manager_id)


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Project:
    project = _get_project_or_404(db, project_id)
    has_task = not authz.is_manager_or_admin(current_user) and _employee_has_task_in(db, project_id, current_user.id)
    if not authz.can_view_project(current_user, has_task_in_project=has_task):
        raise forbidden("You may only view a project you have a task in.")
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int, data: ProjectUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Project:
    project = _get_project_or_404(db, project_id)
    if not authz.can_modify_project(current_user, project):
        raise forbidden("Only this project's manager or an admin may edit it.")
    try:
        return project_service.update_project(db, project, data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reference (e.g. manager_id does not exist)"
        ) from exc


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> None:
    project = _get_project_or_404(db, project_id)
    if not authz.can_modify_project(current_user, project):
        raise forbidden("Only this project's manager or an admin may delete it.")
    project_service.delete_project(db, project)
