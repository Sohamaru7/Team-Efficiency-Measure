"""DB-aware orchestration: fetch rows, then delegate to the pure functions in `metrics.py`.

Only `calculate_employee_score` and `calculate_team_score` live here — every other analytics
function is pure (see `metrics.py`) and doesn't need a database session at all. This module is
the thin, deliberately unglamorous layer that wires "fetch the relevant tasks/users" to "run the
formulas," and combines the per-component metrics into the weighted overall score described in
the Phase 4 brief.
"""

from __future__ import annotations

from datetime import date
from statistics import mean

from sqlalchemy.orm import Session

from app.services import task_service, user_service
from app.services.analytics.constants import (
    DEFAULT_CAPACITY_HOURS,
    INDIVIDUAL_SCORE_WEIGHTS,
    MAX_ANALYTICS_ROWS,
)
from app.services.analytics.metrics import (
    calculate_project_progress,
    calculate_workload,
    deadline_adherence_rate,
    on_time_completion_rate,
    quality_score_metric,
    task_completion_rate,
    time_efficiency_score,
)
from app.services.analytics.results import EmployeeScoreResult, ScoreComponent, TeamScoreResult

_MAX_ROWS = MAX_ANALYTICS_ROWS

_TASK_COUNT_STATUSES = (
    "not_started",
    "in_progress",
    "blocked",
    "completed",
    "cancelled",
)


def _weighted_average(
    values: dict[str, float | None], weights: dict[str, float]
) -> tuple[float | None, dict[str, float]]:
    """Combine component scores per `weights`, excluding None components and renormalizing
    the remaining weights so they still sum to 1.0. This is what lets a new employee who has,
    say, only completion-rate data yet still get a meaningful overall score instead of being
    dragged toward 0 by components that simply have no data.

    Returns (overall_score_or_None, applied_weights_used).
    """
    available = {k: v for k, v in values.items() if v is not None}
    if not available:
        return None, {}
    weight_sum = sum(weights[k] for k in available)
    if weight_sum <= 0:
        return None, {}
    applied = {k: weights[k] / weight_sum for k in available}
    overall = sum(available[k] * applied[k] for k in available)
    return overall, applied


def calculate_employee_score(
    db: Session,
    user_id: int,
    *,
    as_of: date | None = None,
    capacity_hours: float = DEFAULT_CAPACITY_HOURS,
) -> EmployeeScoreResult:
    """8. Individual efficiency score.

    Fetches every task currently assigned to `user_id` and combines the metrics in
    `metrics.py` into one weighted 0-100 score, per the Phase 4 weight table
    (`INDIVIDUAL_SCORE_WEIGHTS`):

        completion (25%) + on_time (20%) + quality (15%) + time_efficiency (15%)
        + deadline_adherence (10%) + project_progress (10%) + workload (5%)

    A component that has no data (e.g. no completed tasks yet, so `quality` is undefined) is
    dropped from the sum and the remaining weights are renormalized to still total 1.0 — see
    `_weighted_average`. `workload` is the one component that is always defined (0 active tasks
    is a valid 0% utilization), so a user with zero tasks still gets an `overall_score` — it
    just equals their (zero) workload score, since every other component has no data yet. That
    is intentional: it is a real, low-but-defined score rather than a hidden `None`, since an
    idle employee with no assigned work is itself a meaningful state to surface.

    `project_progress` is the average, across every *distinct* project the user has a task in,
    of that project's overall (project-wide, not just this user's) weighted progress — see
    `metrics.calculate_project_progress`. Each project counts equally regardless of how many of
    the user's own tasks are in it.
    """
    as_of = as_of or date.today()
    tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, assigned_to=user_id)

    completion = task_completion_rate(tasks)
    on_time = on_time_completion_rate(tasks)
    quality = quality_score_metric(tasks)
    time_eff = time_efficiency_score(tasks)
    deadline_adh = deadline_adherence_rate(tasks, as_of)
    workload_result = calculate_workload(tasks, capacity_hours)

    project_ids = sorted({t.project_id for t in tasks})
    project_progress_values: list[float] = []
    for project_id in project_ids:
        project_tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, project_id=project_id)
        project_progress_values.append(calculate_project_progress(project_tasks, project_id).progress_pct)
    project_progress = mean(project_progress_values) if project_progress_values else None

    raw_components: dict[str, float | None] = {
        "completion": completion,
        "on_time": on_time,
        "quality": quality,
        "time_efficiency": time_eff,
        "deadline_adherence": deadline_adh,
        "project_progress": project_progress,
        "workload": workload_result.score,
    }

    overall, applied_weights = _weighted_average(raw_components, INDIVIDUAL_SCORE_WEIGHTS)

    non_cancelled = [t for t in tasks if t.status.value != "cancelled"]
    sample_sizes = {
        "completion": len(non_cancelled),
        "on_time": sum(1 for t in tasks if t.status.value == "completed" and t.deadline is not None and t.completed_date is not None),
        "quality": sum(1 for t in tasks if t.status.value == "completed" and t.quality_score is not None),
        "time_efficiency": sum(
            1
            for t in tasks
            if t.status.value == "completed" and t.estimated_hours is not None and t.actual_hours is not None
        ),
        "deadline_adherence": sum(1 for t in non_cancelled if t.deadline is not None),
        "project_progress": len(project_ids),
        "workload": workload_result.active_task_count,
    }

    components = {
        name: ScoreComponent(
            value=raw_components[name],
            weight=INDIVIDUAL_SCORE_WEIGHTS[name],
            applied_weight=applied_weights.get(name, 0.0),
            sample_size=sample_sizes[name],
        )
        for name in INDIVIDUAL_SCORE_WEIGHTS
    }

    task_counts = {"total": len(tasks)}
    for status_value in _TASK_COUNT_STATUSES:
        task_counts[status_value] = sum(1 for t in tasks if t.status.value == status_value)

    return EmployeeScoreResult(
        user_id=user_id,
        as_of=as_of,
        overall_score=overall,
        components=components,
        task_counts=task_counts,
        workload=workload_result,
        projects_considered=project_ids,
    )


def calculate_team_score(
    db: Session,
    *,
    user_ids: list[int] | None = None,
    department: str | None = None,
    as_of: date | None = None,
    capacity_hours: float = DEFAULT_CAPACITY_HOURS,
) -> TeamScoreResult:
    """9. Team efficiency score.

    Resolves a set of users, computes `calculate_employee_score` for each, and averages the
    results. Resolution order:

      1. `user_ids` given -> use exactly that list (de-duplicated, order preserved).
      2. else `department` given -> every *active* user in that department.
      3. else -> every active user (whole-organization team score).

    `overall_score` is the plain mean of members' `overall_score` values that are not None;
    members with no computable score (see `calculate_employee_score`) are excluded from the
    average but still appear in `.members` and count toward `member_count`, with
    `scored_member_count` reporting how many actually contributed. `component_averages` does
    the same per-component (e.g. the team's average quality score, ignoring members with no
    quality data yet).
    """
    as_of = as_of or date.today()

    if user_ids:
        resolved_ids = list(dict.fromkeys(user_ids))
    else:
        users = user_service.list_users(db, skip=0, limit=_MAX_ROWS, active=True)
        if department is not None:
            users = [u for u in users if u.department == department]
        resolved_ids = [u.id for u in users]

    members = [
        calculate_employee_score(db, uid, as_of=as_of, capacity_hours=capacity_hours)
        for uid in resolved_ids
    ]
    scored = [m for m in members if m.overall_score is not None]
    overall = mean(m.overall_score for m in scored) if scored else None

    component_averages: dict[str, float | None] = {}
    for key in INDIVIDUAL_SCORE_WEIGHTS:
        values = [m.components[key].value for m in members if m.components[key].value is not None]
        component_averages[key] = mean(values) if values else None

    return TeamScoreResult(
        as_of=as_of,
        member_count=len(members),
        scored_member_count=len(scored),
        overall_score=overall,
        component_averages=component_averages,
        members=members,
    )
