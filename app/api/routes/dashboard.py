from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import forbidden, require_manager_or_admin
from app.database.session import get_db
from app.models.enums import TaskStatus
from app.models.user import User
from app.schemas.dashboard import ManagerDashboardSchema
from app.services import authz, project_service, user_service
from app.services.analytics.constants import DEFAULT_CAPACITY_HOURS
from app.services.analytics.dashboard import get_manager_dashboard

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=ManagerDashboardSchema)
def get_dashboard(
    employee_id: int | None = Query(default=None, description="Restrict to one employee"),
    department: str | None = Query(default=None, description="Restrict to one department (ignored if employee_id is set)"),
    project_id: int | None = Query(default=None, description="Restrict to one project"),
    status_filter: TaskStatus | None = Query(default=None, alias="status", description="Restrict to one task status"),
    date_from: date | None = Query(default=None, description="Start of the date window (see README for per-section semantics)"),
    date_to: date | None = Query(default=None, description="End of the date window"),
    as_of: date | None = Query(default=None, description="Reference date for deadline/risk calculations (default: today)"),
    capacity_hours: float = Query(default=DEFAULT_CAPACITY_HOURS, gt=0, description="Expected working hours per employee for the period"),
    upcoming_limit: int = Query(default=10, ge=1, le=100, description="Max rows in the upcoming-deadlines table"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_admin),
) -> ManagerDashboardSchema:
    """The full manager dashboard: summary KPIs, employee performance, workload distribution,
    project progress, delayed tasks, upcoming deadlines, and the efficiency trend — all computed
    in Python from one consistent set of filters. See `app.services.analytics.dashboard` for the
    exact filter semantics (in particular, what "date range" means per section). Manager/admin
    only; a plain manager is always restricted to their own team (see `/api/analytics/team/score`
    for the identical restriction pattern).
    """
    employee = user_service.get_user(db, employee_id) if employee_id is not None else None
    if employee_id is not None and employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    if project_id is not None and project_service.get_project(db, project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="date_from must be on or before date_to")

    if not authz.is_admin(current_user):
        if employee is not None and not authz.same_team(current_user, employee):
            raise forbidden("You may only view your own team's dashboard.")
        if employee is None:
            department = current_user.department

    result = get_manager_dashboard(
        db,
        employee_id=employee_id,
        department=department,
        project_id=project_id,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
        as_of=as_of,
        capacity_hours=capacity_hours,
        upcoming_limit=upcoming_limit,
    )
    return ManagerDashboardSchema.model_validate(result)
