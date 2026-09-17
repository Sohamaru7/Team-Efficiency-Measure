"""Row-level validation: turns one mapped row (canonical field -> raw string) into either
ready-to-use `TaskCreate` kwargs, or a list of human-readable errors. Never raises — a row with
bad data is reported, not an exception that would abort the whole file. Reference fields
(Employee, Project) are resolved against real `User`/`Project` rows looked up by the caller
(passed in as name-keyed caches built once per import, not re-queried per row) — an unresolved
employee or project is a validation error, never silently dropped or auto-created, per "do not
blindly import invalid data."
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.enums import TaskPriority, TaskStatus
from app.models.project import Project
from app.models.user import User

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y")


@dataclass
class RowValidation:
    errors: list[str] = field(default_factory=list)
    task_kwargs: dict[str, Any] | None = None
    employee_display: str | None = None
    project_display: str | None = None
    task_display: str | None = None


def validate_row(
    mapped: dict[str, str | None],
    projects_by_name: dict[str, Project],
    users_by_name: dict[str, User],
) -> RowValidation:
    errors: list[str] = []

    project_raw = (mapped.get("project") or "").strip()
    task_raw = (mapped.get("task") or "").strip()
    employee_raw = (mapped.get("employee") or "").strip()

    project = None
    if not project_raw:
        errors.append("Project is required")
    else:
        project = projects_by_name.get(project_raw.lower())
        if project is None:
            errors.append(f"Unknown project: {project_raw!r}")

    if not task_raw:
        errors.append("Task is required")
    elif len(task_raw) > 255:
        errors.append("Task title is too long (max 255 characters)")

    assigned_to = None
    if employee_raw:
        user = users_by_name.get(employee_raw.lower())
        if user is None:
            errors.append(f"Unknown employee: {employee_raw!r}")
        else:
            assigned_to = user.id

    priority, priority_error = _parse_choice(mapped.get("priority"), TaskPriority, TaskPriority.MEDIUM, "Priority")
    if priority_error:
        errors.append(priority_error)

    status, status_error = _parse_choice(mapped.get("status"), TaskStatus, TaskStatus.NOT_STARTED, "Status")
    if status_error:
        errors.append(status_error)

    estimated_hours, est_error = _parse_decimal(mapped.get("estimated_hours"), "Estimated Hours", min_value=0)
    if est_error:
        errors.append(est_error)

    actual_hours, actual_error = _parse_decimal(mapped.get("actual_hours"), "Actual Hours", min_value=0)
    if actual_error:
        errors.append(actual_error)

    quality, quality_error = _parse_decimal(mapped.get("quality"), "Quality", min_value=0, max_value=100)
    if quality_error:
        errors.append(quality_error)

    start_date, start_error = _parse_date(mapped.get("start_date"), "Start Date")
    if start_error:
        errors.append(start_error)

    deadline, deadline_error = _parse_date(mapped.get("deadline"), "Deadline")
    if deadline_error:
        errors.append(deadline_error)

    if start_date and deadline and deadline < start_date:
        errors.append("Deadline must be on or after Start Date")

    delay_reason = (mapped.get("delay_reason") or "").strip() or None

    if errors:
        return RowValidation(
            errors=errors, employee_display=employee_raw or None, project_display=project_raw or None, task_display=task_raw or None
        )

    task_kwargs = {
        "project_id": project.id,
        "assigned_to": assigned_to,
        "title": task_raw,
        "priority": priority,
        "estimated_hours": estimated_hours,
        "actual_hours": actual_hours,
        "start_date": start_date,
        "deadline": deadline,
        "status": status,
        "quality_score": quality,
        "delay_reason": delay_reason,
    }
    return RowValidation(
        errors=[],
        task_kwargs=task_kwargs,
        employee_display=employee_raw or None,
        project_display=project_raw,
        task_display=task_raw,
    )


def _parse_choice(raw: str | None, enum_cls, default, label: str):
    text = (raw or "").strip()
    if not text:
        return default, None
    key = re.sub(r"[\s\-]+", "_", text.strip().lower())
    try:
        return enum_cls(key), None
    except ValueError:
        valid = ", ".join(v.value for v in enum_cls)
        return None, f"{label} {raw!r} is not one of: {valid}"


def _parse_decimal(raw: str | None, label: str, *, min_value: float | None = None, max_value: float | None = None):
    text = (raw or "").strip()
    if not text:
        return None, None
    cleaned = text.replace(",", "").replace("$", "").strip()
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None, f"{label} {raw!r} is not a valid number"
    if min_value is not None and value < min_value:
        return None, f"{label} must be >= {min_value}"
    if max_value is not None and value > max_value:
        return None, f"{label} must be <= {max_value}"
    return value, None


def _parse_date(raw: str | None, label: str):
    text = (raw or "").strip()
    if not text:
        return None, None
    # Excel dates arrive already ISO-formatted by parsing.py (`_cell_to_str`); a datetime with a
    # time component is truncated to its date, since Task.start_date/deadline are date-only.
    if "T" in text:
        text = text.split("T", 1)[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date(), None
        except ValueError:
            continue
    return None, f"{label} {raw!r} is not a recognized date (use YYYY-MM-DD or MM/DD/YYYY)"
