from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import forbidden, get_current_user, require_manager_or_admin
from app.database.session import get_db
from app.models.user import User
from app.schemas.analytics import (
    EmployeeScoreSchema,
    ProjectProgressSchema,
    TaskDeadlineRiskSchema,
    TaskDelaySchema,
    TeamScoreSchema,
    WorkloadSchema,
)
from app.services import authz, project_service, task_service, user_service
from app.services.analytics import (
    calculate_employee_score,
    calculate_project_progress,
    calculate_team_score,
    calculate_workload,
    detect_deadline_risk,
    detect_delays,
)
from app.services.analytics.constants import DEFAULT_CAPACITY_HOURS
from app.services.analytics.results import DeadlineRiskLevel

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_MAX_ROWS = 10_000


def _require_viewable_user(db: Session, user_id: int, current_user: User) -> None:
    target = user_service.get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not authz.can_view_user(current_user, target):
        raise forbidden("You may only view your own analytics or your team's.")


def _require_project(db: Session, project_id: int) -> None:
    if project_service.get_project(db, project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.get("/employees/{user_id}/score", response_model=EmployeeScoreSchema)
def get_employee_score(
    user_id: int,
    as_of: date | None = Query(default=None, description="Date to evaluate deadlines against (default: today)"),
    capacity_hours: float = Query(default=DEFAULT_CAPACITY_HOURS, gt=0, description="Expected working hours for the period"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmployeeScoreSchema:
    """Individual efficiency score (0-100) plus every weighted component that feeds it."""
    _require_viewable_user(db, user_id, current_user)
    result = calculate_employee_score(db, user_id, as_of=as_of, capacity_hours=capacity_hours)
    return EmployeeScoreSchema.model_validate(result)


@router.get("/employees/{user_id}/workload", response_model=WorkloadSchema)
def get_employee_workload(
    user_id: int,
    capacity_hours: float = Query(default=DEFAULT_CAPACITY_HOURS, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkloadSchema:
    """Standalone workload utilization for one employee's currently open tasks."""
    _require_viewable_user(db, user_id, current_user)
    tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, assigned_to=user_id)
    result = calculate_workload(tasks, capacity_hours)
    return WorkloadSchema.model_validate(result)


@router.get("/employees/{user_id}/deadline-risk", response_model=list[TaskDeadlineRiskSchema])
def get_employee_deadline_risk(
    user_id: int,
    as_of: date | None = Query(default=None),
    min_risk: DeadlineRiskLevel | None = Query(
        default=None, description="Only return tasks at or above this risk level"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TaskDeadlineRiskSchema]:
    """Forward-looking deadline-risk classification for one employee's tasks, most severe first."""
    _require_viewable_user(db, user_id, current_user)
    tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, assigned_to=user_id)
    results = detect_deadline_risk(tasks, as_of)
    if min_risk is not None:
        severity = {"overdue": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
        threshold = severity[min_risk.value]
        results = [r for r in results if severity[r.risk.value] <= threshold]
    return [TaskDeadlineRiskSchema.model_validate(r) for r in results]


@router.get("/employees/{user_id}/delays", response_model=list[TaskDelaySchema])
def get_employee_delays(
    user_id: int,
    as_of: date | None = Query(default=None),
    only_delayed: bool = Query(default=True, description="If true, only return currently/previously late tasks"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TaskDelaySchema]:
    """Actual delay status for one employee's tasks (not a prediction — see deadline-risk for that)."""
    _require_viewable_user(db, user_id, current_user)
    tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, assigned_to=user_id)
    results = detect_delays(tasks, as_of)
    if only_delayed:
        results = [r for r in results if r.is_delayed]
    return [TaskDelaySchema.model_validate(r) for r in results]


@router.get("/projects/{project_id}/progress", response_model=ProjectProgressSchema)
def get_project_progress(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_manager_or_admin)
) -> ProjectProgressSchema:
    """Difficulty-weighted completion percentage for one project, across all of its tasks.
    Manager/admin only — this is a project-wide aggregate, not one employee's own data.
    """
    _require_project(db, project_id)
    tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, project_id=project_id)
    result = calculate_project_progress(tasks, project_id)
    return ProjectProgressSchema.model_validate(result)


@router.get("/team/score", response_model=TeamScoreSchema)
def get_team_score(
    user_ids: list[int] | None = Query(default=None, description="Explicit member list; overrides department"),
    department: str | None = Query(default=None, description="Score every active user in this department"),
    as_of: date | None = Query(default=None),
    capacity_hours: float = Query(default=DEFAULT_CAPACITY_HOURS, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_admin),
) -> TeamScoreSchema:
    """Team efficiency score: the average individual score across a resolved set of members.

    Resolution: explicit `user_ids` if given, else every active user in `department` if given,
    else every active user in the system. A plain manager (not admin) is always restricted to
    their own team no matter what's requested: an explicit `user_ids` list is rejected (403) if
    it names anyone outside their department, and `department`/unset both resolve to the
    manager's own department rather than "everyone."
    """
    if not authz.is_admin(current_user):
        if user_ids:
            targets = [user_service.get_user(db, uid) for uid in user_ids]
            if any(t is None or not authz.same_team(current_user, t) for t in targets):
                raise forbidden("You may only score your own team.")
        else:
            department = current_user.department

    result = calculate_team_score(
        db, user_ids=user_ids, department=department, as_of=as_of, capacity_hours=capacity_hours
    )
    return TeamScoreSchema.model_validate(result)
