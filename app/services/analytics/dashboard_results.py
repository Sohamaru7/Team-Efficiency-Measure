"""Dataclasses for the manager dashboard (Phase 5) — composed from the Phase 4 primitives in
`results.py` plus a couple of display fields (names) so the frontend can render tables without
doing any lookups or calculations of its own. Kept separate from `results.py` because these are
dashboard-specific *compositions*, not new metrics in their own right.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.services.analytics.results import EmployeeScoreResult, ProjectProgressResult, WorkloadResult


@dataclass
class WorkloadRow:
    """One row of the "Workload distribution" table/chart: one employee's `WorkloadResult`
    plus display fields, scoped to the dashboard's active project/status filters.
    """

    user_id: int
    name: str
    department: str | None
    workload: WorkloadResult


@dataclass
class ProjectProgressRow:
    """One row of the "Project progress" table/chart: a project-wide `ProjectProgressResult`
    (see metrics.calculate_project_progress — always project-wide, not filtered by assignee)
    plus the project's name.
    """

    project_id: int
    name: str
    progress: ProjectProgressResult


@dataclass
class DelayedTaskRow:
    """One row of the "Delayed tasks" table: a `metrics.detect_delays` result restricted to
    `is_delayed == True`, with the assignee's and project's names attached for display.
    """

    task_id: int
    title: str
    project_id: int
    project_name: str
    assignee_id: int | None
    assignee_name: str | None
    status: str
    deadline: date | None
    delay_days: int | None
    delay_reason: str | None


@dataclass
class UpcomingDeadlineRow:
    """One row of the "Upcoming deadlines" table: an open task whose deadline is today or in
    the future, soonest first.
    """

    task_id: int
    title: str
    project_id: int
    project_name: str
    assignee_id: int | None
    assignee_name: str | None
    status: str
    priority: str
    deadline: date
    days_left: int


@dataclass
class TrendPoint:
    """One day's efficiency-trend data point, built from real historical `daily_updates` rows
    (the only genuinely historical, per-day record this system captures — see
    `dashboard.calculate_efficiency_trend`), not a reconstruction or approximation.
    """

    date: date
    avg_completion_ratio: float | None  # tasks_completed / (tasks_completed + tasks_pending) * 100
    tasks_completed: int
    tasks_pending: int
    update_count: int  # number of daily updates rolled into this point


@dataclass
class DashboardSummary:
    as_of: date
    team_size: int
    overall_team_efficiency: float | None
    tasks_completed: int
    tasks_overdue: int
    tasks_at_risk: int
    average_completion_days: float | None
    on_time_completion_rate: float | None
    team_workload: WorkloadResult


@dataclass
class EmployeePerformanceRow:
    """One row of the "Employee performance" table: an `EmployeeScoreResult` (see
    scoring.calculate_employee_score) plus the employee's name/department for display, so the
    frontend never has to join a user id to a name itself.
    """

    user_id: int
    name: str
    department: str | None
    score: EmployeeScoreResult


@dataclass
class ManagerDashboardResult:
    as_of: date
    filters: dict[str, object]
    summary: DashboardSummary
    employee_performance: list[EmployeePerformanceRow] = field(default_factory=list)
    workload_distribution: list[WorkloadRow] = field(default_factory=list)
    project_progress: list[ProjectProgressRow] = field(default_factory=list)
    delayed_tasks: list[DelayedTaskRow] = field(default_factory=list)
    upcoming_deadlines: list[UpcomingDeadlineRow] = field(default_factory=list)
    efficiency_trend: list[TrendPoint] = field(default_factory=list)
