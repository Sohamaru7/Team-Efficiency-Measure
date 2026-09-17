import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import require_manager_or_admin
from app.database.session import get_db
from app.models.enums import TaskStatus
from app.models.user import User
from app.services import project_service, user_service
from app.services.analytics.constants import DEFAULT_CAPACITY_HOURS
from app.services.analytics.dashboard import get_manager_dashboard
from app.services.import_export.export import (
    build_task_rows,
    export_dashboard_csv,
    export_dashboard_xlsx,
    export_tasks_csv,
    export_tasks_xlsx,
)

router = APIRouter(prefix="/api/export", tags=["import-export"])

_CSV_MEDIA_TYPE = "text/csv"
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _validate_format(fmt: str) -> None:
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="format must be 'csv' or 'xlsx'")


def _download_response(content: bytes, fmt: str, base_filename: str) -> StreamingResponse:
    media_type = _CSV_MEDIA_TYPE if fmt == "csv" else _XLSX_MEDIA_TYPE
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{base_filename}.{fmt}"'},
    )


@router.get("/tasks")
def export_tasks(
    format: str = Query(default="csv", description="'csv' or 'xlsx'"),
    project_id: int | None = Query(default=None),
    employee_id: int | None = Query(default=None),
    department: str | None = Query(default=None),
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_admin),
) -> StreamingResponse:
    """Export the raw task list in the same canonical columns the importer understands — a
    round-trippable file, and a good way to check what the current data looks like before
    editing and re-importing it. Manager/admin only.
    """
    _validate_format(format)
    if project_id is not None and project_service.get_project(db, project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if employee_id is not None and user_service.get_user(db, employee_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    tasks = build_task_rows(
        db, project_id=project_id, employee_id=employee_id, department=department, status=status_filter
    )
    content = export_tasks_csv(tasks) if format == "csv" else export_tasks_xlsx(tasks)
    return _download_response(content, format, "tasks")


@router.get("/dashboard")
def export_dashboard(
    format: str = Query(default="csv", description="'csv' or 'xlsx'"),
    employee_id: int | None = Query(default=None),
    department: str | None = Query(default=None),
    project_id: int | None = Query(default=None),
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    as_of: date | None = Query(default=None),
    capacity_hours: float = Query(default=DEFAULT_CAPACITY_HOURS, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_admin),
) -> StreamingResponse:
    """Export the same sections the Manager Dashboard shows (summary KPIs, employee
    performance, workload, project progress, delayed tasks, upcoming deadlines) for the given
    filters — CSV writes one section after another, XLSX writes one sheet per section. Reuses
    `get_manager_dashboard` directly, so this always matches what the dashboard page shows.
    Manager/admin only.
    """
    _validate_format(format)
    if employee_id is not None and user_service.get_user(db, employee_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    if project_id is not None and project_service.get_project(db, project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="date_from must be on or before date_to")

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
    )
    content = export_dashboard_csv(result) if format == "csv" else export_dashboard_xlsx(result)
    return _download_response(content, format, "manager_dashboard")
