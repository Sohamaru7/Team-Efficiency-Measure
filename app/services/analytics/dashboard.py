"""Manager dashboard (Phase 5): one DB-aware orchestration function, `get_manager_dashboard`,
that resolves a set of filters (date range, employee, department, project, task status) once and
composes every dashboard section from them using the Phase 4 primitives in `metrics.py`/
`scoring.py`, plus two new pieces of logic this phase adds:

- `average_completion_days` (metrics.py) — a plain descriptive statistic Phase 4 didn't need.
- `calculate_efficiency_trend` (below) — a genuine historical time series built from the
  `daily_updates` table (Phase 2/3), since Phase 4's scores are explicitly point-in-time
  snapshots with no persisted history to trend over.

Every number here is computed in Python before the response is serialized — the frontend only
formats and renders what this module (via the API layer) already computed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.daily_update import DailyUpdate
from app.models.enums import TaskStatus
from app.models.task import Task
from app.services import project_service, task_service, user_service
from app.services.analytics.constants import (
    DEFAULT_CAPACITY_HOURS,
    DEFAULT_TREND_WINDOW_DAYS,
    MAX_ANALYTICS_ROWS,
)
from app.services.analytics.dashboard_results import (
    DashboardSummary,
    DelayedTaskRow,
    EmployeePerformanceRow,
    ManagerDashboardResult,
    ProjectProgressRow,
    TrendPoint,
    UpcomingDeadlineRow,
    WorkloadRow,
)
from app.services.analytics.metrics import (
    OPEN_STATUSES,
    average_completion_days,
    calculate_project_progress,
    calculate_workload,
    detect_deadline_risk,
    detect_delays,
    on_time_completion_rate,
    task_weight,
    workload_score_from_utilization,
)
from app.services.analytics.results import DeadlineRiskLevel, WorkloadResult
from app.services.analytics.scoring import calculate_employee_score, calculate_team_score

_MAX_ROWS = MAX_ANALYTICS_ROWS


def in_date_range(value: date | None, date_from: date | None, date_to: date | None) -> bool:
    """A dated field is "in range" only if it has a date at all — an undated task/record can't
    be placed inside a specific window, so it's excluded rather than assumed to match.

    Public (not module-private) because `app.services.ai.tools` reuses the exact same
    date-window semantics documented here and in `get_manager_dashboard`.
    """
    if value is None:
        return False
    if date_from is not None and value < date_from:
        return False
    if date_to is not None and value > date_to:
        return False
    return True


def calculate_efficiency_trend(
    db: Session, *, user_ids: list[int], date_from: date, date_to: date
) -> list[TrendPoint]:
    """A genuine historical time series, unlike the rest of this package's point-in-time
    snapshots — built from `daily_updates`, the only per-day record employees themselves
    submit (Phase 3's Daily Work Update page).

    For each calendar date in [date_from, date_to] that has at least one DailyUpdate from a
    user in `user_ids`:

        tasks_completed = Σ tasks_completed across that date's updates
        tasks_pending    = Σ tasks_pending across that date's updates
        avg_completion_ratio = tasks_completed / (tasks_completed + tasks_pending) × 100
            (None for a date where every update that day reported 0 completed and 0 pending)

    Dates with no submitted updates are omitted entirely (not filled with a 0) — a gap in the
    trend reflects a gap in reporting, not a claim that zero work happened that day.
    """
    if not user_ids:
        return []

    stmt = (
        select(DailyUpdate)
        .where(DailyUpdate.user_id.in_(user_ids))
        .where(DailyUpdate.date >= date_from)
        .where(DailyUpdate.date <= date_to)
    )
    updates_by_date: dict[date, list[DailyUpdate]] = defaultdict(list)
    for update in db.scalars(stmt):
        updates_by_date[update.date].append(update)

    points = []
    for day in sorted(updates_by_date):
        day_updates = updates_by_date[day]
        completed = sum(u.tasks_completed for u in day_updates)
        pending = sum(u.tasks_pending for u in day_updates)
        total = completed + pending
        ratio = (completed / total * 100.0) if total > 0 else None
        points.append(
            TrendPoint(
                date=day,
                avg_completion_ratio=ratio,
                tasks_completed=completed,
                tasks_pending=pending,
                update_count=len(day_updates),
            )
        )
    return points


def resolve_scope_tasks(
    db: Session,
    *,
    employee_id: int | None,
    department_user_ids: list[int] | None,
    project_id: int | None,
    status: TaskStatus | None,
) -> list[Task]:
    """Fetch tasks filtered by employee/department/project/status (SQL `WHERE`, no date
    filtering — see `in_date_range` for that). Shared by `get_manager_dashboard` and the AI
    assistant's read-only tools (`app.services.ai.tools`), so both use identical filtering.
    """
    stmt = select(Task)
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if employee_id is not None:
        stmt = stmt.where(Task.assigned_to == employee_id)
    elif department_user_ids is not None:
        if not department_user_ids:
            return []
        stmt = stmt.where(Task.assigned_to.in_(department_user_ids))
    if status is not None:
        stmt = stmt.where(Task.status == status)
    stmt = stmt.order_by(Task.id).limit(_MAX_ROWS)
    return list(db.scalars(stmt))


def get_manager_dashboard(
    db: Session,
    *,
    employee_id: int | None = None,
    department: str | None = None,
    project_id: int | None = None,
    status: TaskStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    as_of: date | None = None,
    capacity_hours: float = DEFAULT_CAPACITY_HOURS,
    upcoming_limit: int = 10,
) -> ManagerDashboardResult:
    """Compose the full manager dashboard from one consistent set of filters.

    Filter semantics
    -----------------
    - `employee_id` / `department` narrow the *team* (mutually exclusive; `employee_id` wins if
      both are given). Neither given -> team scope depends on `project_id`: if a project is
      selected, the team is whoever currently has a task in it; otherwise it's every active user.
    - `project_id` / `status` narrow the *task scope* directly (SQL `WHERE`).
    - `date_from` / `date_to` are applied differently depending on what's being measured, because
      "date range" means different things for different numbers on this dashboard:
        * for deadline-anchored views (overdue, at-risk, delayed tasks, upcoming deadlines) the
          range filters each task's `deadline` — "what's due in this window."
        * for completion-anchored views (tasks completed, average completion time, on-time rate)
          the range filters `completed_date` — "what finished in this window."
        * for the efficiency trend, the range filters `daily_updates.date` directly, defaulting
          to the trailing `DEFAULT_TREND_WINDOW_DAYS` days ending at `as_of` if not given.
      Leaving both unset means "no restriction" for every one of these.
    """
    as_of = as_of or date.today()

    department_user_ids: list[int] | None = None
    if employee_id is None and department is not None:
        dept_users = [u for u in user_service.list_users(db, limit=_MAX_ROWS, active=True) if u.department == department]
        department_user_ids = [u.id for u in dept_users]

    scope_tasks = resolve_scope_tasks(
        db,
        employee_id=employee_id,
        department_user_ids=department_user_ids,
        project_id=project_id,
        status=status,
    )

    # Resolve the team's user ids per the precedence documented above.
    if employee_id is not None:
        team_user_ids = [employee_id]
    elif department_user_ids is not None:
        team_user_ids = department_user_ids
    elif project_id is not None:
        team_user_ids = sorted({t.assigned_to for t in scope_tasks if t.assigned_to is not None})
        if not team_user_ids:
            team_user_ids = [u.id for u in user_service.list_users(db, limit=_MAX_ROWS, active=True)]
    else:
        team_user_ids = [u.id for u in user_service.list_users(db, limit=_MAX_ROWS, active=True)]

    has_date_filter = date_from is not None or date_to is not None
    deadline_window_tasks = (
        [t for t in scope_tasks if in_date_range(t.deadline, date_from, date_to)] if has_date_filter else scope_tasks
    )
    completed_window_tasks = [
        t
        for t in scope_tasks
        if t.status == TaskStatus.COMPLETED
        and (in_date_range(t.completed_date, date_from, date_to) if has_date_filter else True)
    ]

    # Lookup maps for display fields, fetched once and reused across every section below.
    project_names = {p.id: p.name for p in project_service.list_projects(db, skip=0, limit=_MAX_ROWS)}
    user_names = {u.id: u.name for u in user_service.list_users(db, skip=0, limit=_MAX_ROWS)}
    user_departments = {u.id: u.department for u in user_service.list_users(db, skip=0, limit=_MAX_ROWS)}

    # --- Summary tile numbers ---------------------------------------------------------------
    risks = detect_deadline_risk(deadline_window_tasks, as_of)
    tasks_overdue = sum(1 for r in risks if r.risk == DeadlineRiskLevel.OVERDUE)
    tasks_at_risk = sum(1 for r in risks if r.risk in (DeadlineRiskLevel.HIGH, DeadlineRiskLevel.MEDIUM))

    team_score = calculate_team_score(db, user_ids=team_user_ids, as_of=as_of, capacity_hours=capacity_hours)

    team_active = [t for t in scope_tasks if t.status in OPEN_STATUSES]
    team_active_hours = sum(task_weight(t) for t in team_active)
    team_capacity_hours = capacity_hours * max(len(team_user_ids), 1)
    team_utilization_pct = (team_active_hours / team_capacity_hours * 100.0) if team_capacity_hours > 0 else 0.0
    team_workload = WorkloadResult(
        active_hours=team_active_hours,
        capacity_hours=team_capacity_hours,
        utilization_pct=team_utilization_pct,
        score=workload_score_from_utilization(team_utilization_pct),
        active_task_count=len(team_active),
    )

    summary = DashboardSummary(
        as_of=as_of,
        team_size=len(team_user_ids),
        overall_team_efficiency=team_score.overall_score,
        tasks_completed=len(completed_window_tasks),
        tasks_overdue=tasks_overdue,
        tasks_at_risk=tasks_at_risk,
        average_completion_days=average_completion_days(completed_window_tasks),
        on_time_completion_rate=on_time_completion_rate(completed_window_tasks),
        team_workload=team_workload,
    )

    # --- Employee performance table ---------------------------------------------------------
    employee_performance = [
        EmployeePerformanceRow(
            user_id=uid,
            name=user_names.get(uid, f"User #{uid}"),
            department=user_departments.get(uid),
            score=calculate_employee_score(db, uid, as_of=as_of, capacity_hours=capacity_hours),
        )
        for uid in team_user_ids
    ]
    employee_performance.sort(key=lambda row: (row.score.overall_score is None, -(row.score.overall_score or 0)))

    # --- Workload distribution table/chart --------------------------------------------------
    workload_distribution = []
    for uid in team_user_ids:
        member_tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, assigned_to=uid, project_id=project_id, status=status)
        workload_distribution.append(
            WorkloadRow(
                user_id=uid,
                name=user_names.get(uid, f"User #{uid}"),
                department=user_departments.get(uid),
                workload=calculate_workload(member_tasks, capacity_hours),
            )
        )
    workload_distribution.sort(key=lambda row: row.workload.utilization_pct, reverse=True)

    # --- Project progress table/chart (always project-wide, per metrics.calculate_project_progress) ---
    if project_id is not None:
        relevant_project_ids = [project_id]
    else:
        relevant_project_ids = sorted({t.project_id for t in scope_tasks})
    project_progress = []
    for pid in relevant_project_ids:
        project_tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, project_id=pid)
        project_progress.append(
            ProjectProgressRow(
                project_id=pid,
                name=project_names.get(pid, f"Project #{pid}"),
                progress=calculate_project_progress(project_tasks, pid),
            )
        )
    project_progress.sort(key=lambda row: row.progress.progress_pct)

    # --- Delayed tasks table -----------------------------------------------------------------
    delays = detect_delays(deadline_window_tasks, as_of)
    tasks_by_id = {t.id: t for t in deadline_window_tasks}
    delayed_tasks = []
    for d in delays:
        if not d.is_delayed:
            continue
        task = tasks_by_id[d.task_id]
        delayed_tasks.append(
            DelayedTaskRow(
                task_id=d.task_id,
                title=d.title,
                project_id=task.project_id,
                project_name=project_names.get(task.project_id, f"Project #{task.project_id}"),
                assignee_id=task.assigned_to,
                assignee_name=user_names.get(task.assigned_to) if task.assigned_to else None,
                status=d.status,
                deadline=d.deadline,
                delay_days=d.delay_days,
                delay_reason=d.delay_reason,
            )
        )
    delayed_tasks.sort(key=lambda row: row.delay_days or 0, reverse=True)

    # --- Upcoming deadlines table -------------------------------------------------------------
    candidates = [
        t
        for t in deadline_window_tasks
        if t.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED) and t.deadline is not None and t.deadline >= as_of
    ]
    candidates.sort(key=lambda t: t.deadline)
    upcoming_deadlines = [
        UpcomingDeadlineRow(
            task_id=t.id,
            title=t.title,
            project_id=t.project_id,
            project_name=project_names.get(t.project_id, f"Project #{t.project_id}"),
            assignee_id=t.assigned_to,
            assignee_name=user_names.get(t.assigned_to) if t.assigned_to else None,
            status=t.status.value,
            priority=t.priority.value,
            deadline=t.deadline,
            days_left=(t.deadline - as_of).days,
        )
        for t in candidates[:upcoming_limit]
    ]

    # --- Efficiency trend chart ----------------------------------------------------------------
    trend_from = date_from or (as_of - timedelta(days=DEFAULT_TREND_WINDOW_DAYS - 1))
    trend_to = date_to or as_of
    efficiency_trend = calculate_efficiency_trend(db, user_ids=team_user_ids, date_from=trend_from, date_to=trend_to)

    return ManagerDashboardResult(
        as_of=as_of,
        filters={
            "employee_id": employee_id,
            "department": department,
            "project_id": project_id,
            "status": status.value if status is not None else None,
            "date_from": date_from,
            "date_to": date_to,
            "capacity_hours": capacity_hours,
        },
        summary=summary,
        employee_performance=employee_performance,
        workload_distribution=workload_distribution,
        project_progress=project_progress,
        delayed_tasks=delayed_tasks,
        upcoming_deadlines=upcoming_deadlines,
        efficiency_trend=efficiency_trend,
    )
