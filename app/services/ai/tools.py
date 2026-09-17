"""Controlled, read-only tools for the Manager AI Assistant (Phase 6).

Every function here is a thin, JSON-serializing wrapper around the deterministic analytics
functions already built in `app.services.analytics` (Phase 4/5) — the Python analytics engine
remains the sole source of truth for every number the assistant reports. No function in this
module performs its own arithmetic beyond simple dict/list shaping and rounding for display, and
none of them write to the database (there is no update/delete tool here, and none is planned for
this phase — see `app.services.ai.assistant` for how the LLM is restricted to calling exactly
these functions and nothing else, such as raw SQL or ORM access).

`TOOL_DEFINITIONS` is the JSON schema list handed to the Claude API's `tools` parameter.
`TOOL_FUNCTIONS` maps each tool name to the Python callable that implements it — every callable
takes a SQLAlchemy `Session` as its first argument (never exposed to the LLM's schema; the
assistant orchestrator supplies it) plus the LLM-supplied keyword arguments.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import TaskStatus
from app.services import project_service, task_service, user_service
from app.services.analytics.constants import DEFAULT_CAPACITY_HOURS, MAX_ANALYTICS_ROWS
from app.services.analytics.dashboard import in_date_range, resolve_scope_tasks
from app.services.analytics.metrics import (
    calculate_project_progress,
    calculate_workload,
    detect_deadline_risk,
    detect_delays,
    quality_score_metric,
)
from app.services.analytics.results import DeadlineRiskLevel
from app.services.analytics.scoring import calculate_employee_score, calculate_team_score

_MAX_ROWS = MAX_ANALYTICS_ROWS


def _round(value: float | None, digits: int = 1) -> float | None:
    return round(value, digits) if isinstance(value, (int, float)) else value


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _department_user_ids(db: Session, department: str | None) -> list[int] | None:
    if department is None:
        return None
    return [u.id for u in user_service.list_users(db, limit=_MAX_ROWS, active=True) if u.department == department]


def _name_maps(db: Session) -> tuple[dict[int, str], dict[int, str]]:
    project_names = {p.id: p.name for p in project_service.list_projects(db, skip=0, limit=_MAX_ROWS)}
    user_names = {u.id: u.name for u in user_service.list_users(db, skip=0, limit=_MAX_ROWS)}
    return project_names, user_names


def _scope(
    db: Session, *, department: str | None, employee_id: int | None, project_id: int | None, status_value: str | None
) -> list:
    status = TaskStatus(status_value) if status_value else None
    return resolve_scope_tasks(
        db,
        employee_id=employee_id,
        department_user_ids=_department_user_ids(db, department),
        project_id=project_id,
        status=status,
    )


# ------------------------------------------------------------------------------------ tools ----


def get_team_metrics(db: Session, department: str | None = None, as_of: str | None = None) -> dict[str, Any]:
    """Overall team efficiency score and every weighted component average, optionally scoped
    to one department. Wraps `scoring.calculate_team_score` directly — no calculation happens
    here beyond rounding for display.
    """
    team = calculate_team_score(db, department=department, as_of=_parse_date(as_of))
    return {
        "department": department,
        "as_of": str(team.as_of),
        "team_size": team.member_count,
        "scored_member_count": team.scored_member_count,
        "overall_efficiency_score": _round(team.overall_score),
        "component_averages": {k: _round(v) for k, v in team.component_averages.items()},
    }


def get_employee_metrics(db: Session, employee_id: int) -> dict[str, Any]:
    """One employee's full efficiency score breakdown. Wraps
    `scoring.calculate_employee_score` directly.
    """
    user = user_service.get_user(db, employee_id)
    if user is None:
        return {"error": f"No employee with id {employee_id}."}
    score = calculate_employee_score(db, employee_id)
    return {
        "employee_id": employee_id,
        "name": user.name,
        "department": user.department,
        "as_of": str(score.as_of),
        "overall_efficiency_score": _round(score.overall_score),
        "components": {
            k: {"value": _round(v.value), "weight": v.weight, "sample_size": v.sample_size}
            for k, v in score.components.items()
        },
        "task_counts": score.task_counts,
        "workload": {
            "active_hours": _round(score.workload.active_hours),
            "utilization_pct": _round(score.workload.utilization_pct),
            "active_task_count": score.workload.active_task_count,
        },
    }


def get_project_metrics(db: Session, project_id: int) -> dict[str, Any]:
    """One project's difficulty-weighted progress and task breakdown. Wraps
    `metrics.calculate_project_progress` directly (always project-wide, not filtered by
    assignee — see that function's docstring).
    """
    project = project_service.get_project(db, project_id)
    if project is None:
        return {"error": f"No project with id {project_id}."}
    tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, project_id=project_id)
    progress = calculate_project_progress(tasks, project_id)
    return {
        "project_id": project_id,
        "name": project.name,
        "status": project.status.value,
        "deadline": str(project.deadline) if project.deadline else None,
        "progress_pct": _round(progress.progress_pct),
        "total_tasks": progress.total_tasks,
        "completed_tasks": progress.completed_tasks,
        "in_progress_tasks": progress.in_progress_tasks,
        "blocked_tasks": progress.blocked_tasks,
        "not_started_tasks": progress.not_started_tasks,
    }


def get_overdue_tasks(
    db: Session,
    department: str | None = None,
    employee_id: int | None = None,
    project_id: int | None = None,
    as_of: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Tasks currently past their deadline and not yet completed, most overdue first. Wraps
    `metrics.detect_deadline_risk` and filters to the OVERDUE bucket.
    """
    as_of_date = _parse_date(as_of) or date.today()
    tasks = _scope(db, department=department, employee_id=employee_id, project_id=project_id, status_value=None)
    risks = [r for r in detect_deadline_risk(tasks, as_of_date) if r.risk == DeadlineRiskLevel.OVERDUE]
    risks.sort(key=lambda r: r.days_left if r.days_left is not None else 0)
    project_names, user_names = _name_maps(db)
    tasks_by_id = {t.id: t for t in tasks}
    results = []
    for r in risks[:limit]:
        t = tasks_by_id[r.task_id]
        results.append(
            {
                "task_id": r.task_id,
                "title": r.title,
                "status": r.status,
                "deadline": str(r.deadline) if r.deadline else None,
                "days_overdue": -r.days_left if r.days_left is not None else None,
                "assignee": user_names.get(t.assigned_to) if t.assigned_to else None,
                "project": project_names.get(t.project_id),
            }
        )
    return results


def get_at_risk_tasks(
    db: Session,
    department: str | None = None,
    employee_id: int | None = None,
    project_id: int | None = None,
    as_of: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Tasks at HIGH or MEDIUM deadline risk (not yet overdue — see `get_overdue_tasks` for
    those). Wraps `metrics.detect_deadline_risk`.
    """
    as_of_date = _parse_date(as_of) or date.today()
    tasks = _scope(db, department=department, employee_id=employee_id, project_id=project_id, status_value=None)
    risks = [
        r for r in detect_deadline_risk(tasks, as_of_date) if r.risk in (DeadlineRiskLevel.HIGH, DeadlineRiskLevel.MEDIUM)
    ]
    project_names, user_names = _name_maps(db)
    tasks_by_id = {t.id: t for t in tasks}
    results = []
    for r in risks[:limit]:
        t = tasks_by_id[r.task_id]
        results.append(
            {
                "task_id": r.task_id,
                "title": r.title,
                "risk": r.risk.value,
                "reason": r.reason,
                "deadline": str(r.deadline) if r.deadline else None,
                "days_left": r.days_left,
                "assignee": user_names.get(t.assigned_to) if t.assigned_to else None,
                "project": project_names.get(t.project_id),
            }
        )
    return results


def get_workload(
    db: Session,
    department: str | None = None,
    employee_id: int | None = None,
    capacity_hours: float = DEFAULT_CAPACITY_HOURS,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Workload utilization. Pass `employee_id` for one person's workload, or `department` (or
    neither, for the whole team) for a per-employee list sorted highest-utilization first.
    Wraps `metrics.calculate_workload` directly.
    """
    if employee_id is not None:
        user = user_service.get_user(db, employee_id)
        if user is None:
            return {"error": f"No employee with id {employee_id}."}
        tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, assigned_to=employee_id)
        wl = calculate_workload(tasks, capacity_hours)
        return {
            "employee_id": employee_id,
            "name": user.name,
            "department": user.department,
            "active_hours": _round(wl.active_hours),
            "capacity_hours": wl.capacity_hours,
            "utilization_pct": _round(wl.utilization_pct),
            "active_task_count": wl.active_task_count,
        }

    if department is not None:
        users = [u for u in user_service.list_users(db, limit=_MAX_ROWS, active=True) if u.department == department]
    else:
        users = user_service.list_users(db, limit=_MAX_ROWS, active=True)

    results = []
    for u in users:
        tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, assigned_to=u.id)
        wl = calculate_workload(tasks, capacity_hours)
        results.append(
            {
                "employee_id": u.id,
                "name": u.name,
                "department": u.department,
                "active_hours": _round(wl.active_hours),
                "utilization_pct": _round(wl.utilization_pct),
                "active_task_count": wl.active_task_count,
            }
        )
    results.sort(key=lambda r: r["utilization_pct"], reverse=True)
    return results


def get_recent_delays(
    db: Session,
    days: int = 14,
    department: str | None = None,
    employee_id: int | None = None,
    project_id: int | None = None,
    as_of: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Tasks that were actually late (by deadline) within the last `days` days, with each
    task's human-entered delay reason where available, most-late first. Wraps
    `metrics.detect_delays`, windowed by deadline via the same `in_date_range` helper the
    Manager Dashboard uses.
    """
    as_of_date = _parse_date(as_of) or date.today()
    window_start = as_of_date - timedelta(days=days)
    tasks = _scope(db, department=department, employee_id=employee_id, project_id=project_id, status_value=None)
    windowed = [t for t in tasks if in_date_range(t.deadline, window_start, as_of_date)]
    delays = [d for d in detect_delays(windowed, as_of_date) if d.is_delayed]
    delays.sort(key=lambda d: d.delay_days or 0, reverse=True)
    project_names, user_names = _name_maps(db)
    tasks_by_id = {t.id: t for t in windowed}
    results = []
    for d in delays[:limit]:
        t = tasks_by_id[d.task_id]
        results.append(
            {
                "task_id": d.task_id,
                "title": d.title,
                "status": d.status,
                "deadline": str(d.deadline) if d.deadline else None,
                "delay_days": d.delay_days,
                "delay_reason": d.delay_reason,
                "assignee": user_names.get(t.assigned_to) if t.assigned_to else None,
                "project": project_names.get(t.project_id),
            }
        )
    return results


def get_quality_metrics(
    db: Session, department: str | None = None, employee_id: int | None = None
) -> dict[str, Any]:
    """Quality-score summary (0-100, from completed tasks' recorded `quality_score`): one
    employee's score, or a team/department average plus a per-employee breakdown sorted
    lowest-first so outliers are visible. Wraps `metrics.quality_score_metric`.
    """
    if employee_id is not None:
        user = user_service.get_user(db, employee_id)
        if user is None:
            return {"error": f"No employee with id {employee_id}."}
        tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, assigned_to=employee_id)
        return {"employee_id": employee_id, "name": user.name, "quality_score": _round(quality_score_metric(tasks))}

    if department is not None:
        users = [u for u in user_service.list_users(db, limit=_MAX_ROWS, active=True) if u.department == department]
    else:
        users = user_service.list_users(db, limit=_MAX_ROWS, active=True)

    per_employee = []
    for u in users:
        tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, assigned_to=u.id)
        score = quality_score_metric(tasks)
        if score is not None:
            per_employee.append({"employee_id": u.id, "name": u.name, "quality_score": _round(score)})
    per_employee.sort(key=lambda e: e["quality_score"])

    scores = [e["quality_score"] for e in per_employee]
    team_average = round(sum(scores) / len(scores), 1) if scores else None
    return {"department": department, "team_average_quality_score": team_average, "employees": per_employee}


# --------------------------------------------------------------------------- tool schemas ----

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_team_metrics",
        "description": (
            "Get the team's overall efficiency score and every weighted component average "
            "(completion, on-time, quality, time efficiency, deadline adherence, project "
            "progress, workload), optionally scoped to one department. Use this to answer "
            "'how is the team doing' or as the starting point for 'why did efficiency change' "
            "(call it again with a different as_of date and compare)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {"type": "string", "description": "Restrict to this department. Omit for the whole team."},
                "as_of": {"type": "string", "description": "ISO date (YYYY-MM-DD) to evaluate as of. Omit for today."},
            },
        },
    },
    {
        "name": "get_employee_metrics",
        "description": (
            "Get one employee's full efficiency score breakdown: overall score plus every "
            "weighted component, task counts, and workload."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"employee_id": {"type": "integer", "description": "The employee's user id."}},
            "required": ["employee_id"],
        },
    },
    {
        "name": "get_project_metrics",
        "description": (
            "Get one project's difficulty-weighted completion percentage and a breakdown of "
            "its tasks by status. Use this to answer 'which projects are falling behind' "
            "(call once per project and compare progress_pct)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"project_id": {"type": "integer", "description": "The project's id."}},
            "required": ["project_id"],
        },
    },
    {
        "name": "get_overdue_tasks",
        "description": (
            "List tasks that are currently past their deadline and not yet completed, most "
            "overdue first. Optionally scope to a department, employee, or project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {"type": "string"},
                "employee_id": {"type": "integer"},
                "project_id": {"type": "integer"},
                "as_of": {"type": "string", "description": "ISO date (YYYY-MM-DD). Omit for today."},
                "limit": {"type": "integer", "description": "Max rows to return. Default 20."},
            },
        },
    },
    {
        "name": "get_at_risk_tasks",
        "description": (
            "List tasks at high or medium risk of missing their deadline (not yet overdue). "
            "Use this to answer 'which deadlines are at risk'. Optionally scope to a "
            "department, employee, or project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {"type": "string"},
                "employee_id": {"type": "integer"},
                "project_id": {"type": "integer"},
                "as_of": {"type": "string", "description": "ISO date (YYYY-MM-DD). Omit for today."},
                "limit": {"type": "integer", "description": "Max rows to return. Default 20."},
            },
        },
    },
    {
        "name": "get_workload",
        "description": (
            "Get workload utilization. Pass employee_id for one person, or department (or "
            "neither, for the whole team) for a per-employee list sorted highest-utilization "
            "first. Use this to answer 'who is overloaded' or 'who has unusually high or low "
            "workload'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {"type": "string"},
                "employee_id": {"type": "integer"},
                "capacity_hours": {"type": "number", "description": "Expected hours per employee for the period. Default 40."},
            },
        },
    },
    {
        "name": "get_recent_delays",
        "description": (
            "List tasks that were actually late (by deadline) within the last N days, with "
            "each task's human-entered delay reason. Use this to answer 'what caused recent "
            "delays'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "How many days back to look. Default 14."},
                "department": {"type": "string"},
                "employee_id": {"type": "integer"},
                "project_id": {"type": "integer"},
                "as_of": {"type": "string", "description": "ISO date (YYYY-MM-DD). Omit for today."},
                "limit": {"type": "integer", "description": "Max rows to return. Default 20."},
            },
        },
    },
    {
        "name": "get_quality_metrics",
        "description": (
            "Get quality-score metrics (0-100, from completed tasks' recorded quality scores): "
            "one employee's score, or a team/department average plus a per-employee breakdown "
            "sorted lowest-first so quality outliers are visible."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {"type": "string"},
                "employee_id": {"type": "integer"},
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "get_team_metrics": get_team_metrics,
    "get_employee_metrics": get_employee_metrics,
    "get_project_metrics": get_project_metrics,
    "get_overdue_tasks": get_overdue_tasks,
    "get_at_risk_tasks": get_at_risk_tasks,
    "get_workload": get_workload,
    "get_recent_delays": get_recent_delays,
    "get_quality_metrics": get_quality_metrics,
}
