"""Deterministic issue detection for the manager agent (Phase 7).

Every detector here is plain Python arithmetic over already-computed analytics (Phase 4/5's
`calculate_workload`, `detect_deadline_risk`, `detect_delays`, `calculate_efficiency_trend`) or
direct aggregation of stored data (delay reasons). Nothing here is judged, estimated, or
classified by the LLM — a "problem" is only ever surfaced because a fixed, documented threshold
was crossed by a real number the analytics engine already produced. This is what lets the agent
"detect" issues (the Observe → Analyze → Identify problem steps of the brief's workflow) without
inventing a metric: the classification itself is the thing that must not be invented, so it is
computed here, in code, not asked of the model.

`detect_issues()` is merged into the assistant's read-only tool set in `assistant.py`
(alongside `tools.py`'s eight and `actions.py`'s six), so the assistant can call it exactly like
any other read tool. Imports specific functions from `tools.py` (not the whole module via the
package) so this stays a one-way dependency — `tools.py` never imports `detection.py`.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import ProjectStatus, TaskStatus
from app.services import project_service, task_service, user_service
from app.services.analytics.constants import DEFAULT_CAPACITY_HOURS, MAX_ANALYTICS_ROWS
from app.services.analytics.dashboard import calculate_efficiency_trend
from app.services.analytics.metrics import calculate_project_progress
from app.services.ai.tools import get_at_risk_tasks, get_recent_delays, get_workload

_MAX_ROWS = MAX_ANALYTICS_ROWS

# Fixed, documented thresholds. Changing a number here changes what counts as a "finding" for
# every caller — there is exactly one place these are defined.
OVERLOAD_THRESHOLD_PCT = 100.0  # utilization above this = overloaded
UNDERUTILIZED_THRESHOLD_PCT = 30.0  # utilization below this = underutilized
WORKLOAD_IMBALANCE_SPREAD_PCT = 50.0  # (max - min) utilization across the team above this = imbalance
PERFORMANCE_DROP_THRESHOLD_PCT = 15.0  # drop in avg daily completion ratio (recent half vs earlier half)
PERFORMANCE_DROP_MIN_POINTS = 4  # minimum daily-update data points needed before judging a "drop"
RECURRING_DELAY_MIN_COUNT = 2  # a delay reason must recur at least this many times to be "recurring"
DELAY_LOOKBACK_DAYS = 30  # how far back "delayed tasks" / "recurring causes" look, by deadline

# Phase 10 additions below (QUALITY_ISSUE_THRESHOLD, PROJECT_RISK_*) — `detect_issues()` above
# and its seven findings are completely unchanged; these are new, separate, additive detectors
# for the Autonomous Daily Manager's "quality issues" and "project risks" report sections, not
# folded into `detect_issues()`'s return shape so Phase 7's existing contract (and its tests)
# stay exactly as they were.
QUALITY_ISSUE_THRESHOLD = 60.0  # a completed task's recorded quality_score below this is a "quality issue"
PROJECT_RISK_MAX_DAYS_LEFT = 14  # only projects with a deadline within this many days are considered
PROJECT_RISK_MAX_PROGRESS_PCT = 70.0  # ...and only if difficulty-weighted progress is below this


def _department_users(db: Session, department: str | None) -> list:
    users = user_service.list_users(db, skip=0, limit=_MAX_ROWS, active=True)
    if department is not None:
        users = [u for u in users if u.department == department]
    return users


def _detect_overloaded(workload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [w for w in workload if w["utilization_pct"] > OVERLOAD_THRESHOLD_PCT]


def _detect_underutilized(workload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [w for w in workload if w["utilization_pct"] < UNDERUTILIZED_THRESHOLD_PCT]


def _detect_workload_imbalance(workload: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(workload) < 2:
        return None
    most_loaded = max(workload, key=lambda w: w["utilization_pct"])
    least_loaded = min(workload, key=lambda w: w["utilization_pct"])
    spread = most_loaded["utilization_pct"] - least_loaded["utilization_pct"]
    if spread <= WORKLOAD_IMBALANCE_SPREAD_PCT:
        return None
    return {
        "spread_pct": round(spread, 1),
        "most_loaded": {"employee_id": most_loaded["employee_id"], "name": most_loaded["name"], "utilization_pct": most_loaded["utilization_pct"]},
        "least_loaded": {"employee_id": least_loaded["employee_id"], "name": least_loaded["name"], "utilization_pct": least_loaded["utilization_pct"]},
    }


def _detect_performance_drops(db: Session, users: list, as_of_date: date, window_days: int = 14) -> list[dict[str, Any]]:
    """Compares the average daily completion ratio (from real `daily_updates` rows, via
    `calculate_efficiency_trend`) in the earlier half of the window against the later half, per
    employee. Flags a drop only when there are enough real data points on both sides — an
    employee with sparse or no daily updates yields no claim either way, rather than a false one.
    """
    date_from = as_of_date - timedelta(days=window_days - 1)
    findings = []
    for user in users:
        trend = calculate_efficiency_trend(db, user_ids=[user.id], date_from=date_from, date_to=as_of_date)
        points = [p for p in trend if p.avg_completion_ratio is not None]
        if len(points) < PERFORMANCE_DROP_MIN_POINTS:
            continue
        mid = len(points) // 2
        earlier, later = points[:mid], points[mid:]
        earlier_avg = sum(p.avg_completion_ratio for p in earlier) / len(earlier)
        later_avg = sum(p.avg_completion_ratio for p in later) / len(later)
        drop = earlier_avg - later_avg
        if drop > PERFORMANCE_DROP_THRESHOLD_PCT:
            findings.append(
                {
                    "employee_id": user.id,
                    "name": user.name,
                    "earlier_avg_completion_ratio": round(earlier_avg, 1),
                    "recent_avg_completion_ratio": round(later_avg, 1),
                    "drop_pct": round(drop, 1),
                }
            )
    return findings


def _detect_recurring_delay_causes(delays: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reasons = [d["delay_reason"].strip().lower() for d in delays if d.get("delay_reason")]
    counts = Counter(reasons)
    recurring = [
        {"reason": reason, "occurrences": count}
        for reason, count in counts.items()
        if count >= RECURRING_DELAY_MIN_COUNT
    ]
    recurring.sort(key=lambda r: r["occurrences"], reverse=True)
    return recurring


def detect_issues(
    db: Session,
    department: str | None = None,
    as_of: str | None = None,
    capacity_hours: float = DEFAULT_CAPACITY_HOURS,
) -> dict[str, Any]:
    """Run all seven detectors and return their findings in one structured result. Every list
    below is empty (not omitted) when nothing crosses the relevant threshold, so an empty
    `detect_issues()` result is a real "nothing's wrong" signal, not missing data.
    """
    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    users = _department_users(db, department)

    workload = get_workload(db, department=department, capacity_hours=capacity_hours)
    if isinstance(workload, dict):  # defensive: get_workload returns a dict only when scoped to one employee
        workload = [workload]

    at_risk = get_at_risk_tasks(db, department=department, as_of=as_of, limit=_MAX_ROWS)
    delays = get_recent_delays(db, days=DELAY_LOOKBACK_DAYS, department=department, as_of=as_of, limit=_MAX_ROWS)

    return {
        "as_of": str(as_of_date),
        "department": department,
        "overloaded_employees": _detect_overloaded(workload),
        "underutilized_employees": _detect_underutilized(workload),
        "approaching_deadlines": at_risk,
        "delayed_tasks": delays,
        "performance_drops": _detect_performance_drops(db, users, as_of_date),
        "workload_imbalance": _detect_workload_imbalance(workload),
        "recurring_delay_causes": _detect_recurring_delay_causes(delays),
    }


def detect_quality_issues(
    db: Session, department: str | None = None, as_of: str | None = None, threshold: float = QUALITY_ISSUE_THRESHOLD
) -> list[dict[str, Any]]:
    """Completed tasks with a recorded `quality_score` below `threshold`, lowest first. A task
    with no recorded quality score is not a "quality issue" — absence of a rating is not
    assumed to mean poor quality (same rule `metrics.quality_score_metric` already applies).
    """
    users = _department_users(db, department)
    findings = []
    for user in users:
        tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, assigned_to=user.id, status=TaskStatus.COMPLETED)
        for t in tasks:
            if t.quality_score is None or float(t.quality_score) >= threshold:
                continue
            findings.append(
                {
                    "task_id": t.id,
                    "title": t.title,
                    "employee_id": user.id,
                    "name": user.name,
                    "quality_score": round(float(t.quality_score), 1),
                    "completed_date": str(t.completed_date) if t.completed_date else None,
                }
            )
    findings.sort(key=lambda f: f["quality_score"])
    return findings


def detect_project_risks(
    db: Session,
    as_of: str | None = None,
    max_days_left: int = PROJECT_RISK_MAX_DAYS_LEFT,
    max_progress_pct: float = PROJECT_RISK_MAX_PROGRESS_PCT,
) -> list[dict[str, Any]]:
    """Active projects with a deadline within `max_days_left` days whose difficulty-weighted
    progress (`metrics.calculate_project_progress`, unchanged) is still below `max_progress_pct`
    — i.e. running out of runway before finishing. Projects with no deadline, or already past
    the progress bar, are not flagged.
    """
    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    projects = project_service.list_projects(db, skip=0, limit=_MAX_ROWS, status=ProjectStatus.ACTIVE)
    findings = []
    for p in projects:
        if p.deadline is None:
            continue
        days_left = (p.deadline - as_of_date).days
        if days_left > max_days_left:
            continue
        tasks = task_service.list_tasks(db, skip=0, limit=_MAX_ROWS, project_id=p.id)
        progress = calculate_project_progress(tasks, p.id)
        if progress.progress_pct >= max_progress_pct:
            continue
        findings.append(
            {
                "project_id": p.id,
                "name": p.name,
                "deadline": str(p.deadline),
                "days_left": days_left,
                "progress_pct": round(progress.progress_pct, 1),
            }
        )
    findings.sort(key=lambda f: f["days_left"])
    return findings


DETECTION_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "detect_issues",
        "description": (
            "Scan the team (optionally one department) for problems: overloaded employees, "
            "underutilized employees, tasks approaching their deadline, currently/recently "
            "delayed tasks, unusual drops in daily performance, workload imbalance across the "
            "team, and recurring delay causes. Every finding is computed from fixed thresholds "
            "over real data — call this first when asked to review the team or find problems, "
            "before deciding whether any action is warranted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {"type": "string", "description": "Restrict to this department. Omit for the whole team."},
                "as_of": {"type": "string", "description": "ISO date (YYYY-MM-DD). Omit for today."},
                "capacity_hours": {"type": "number", "description": "Expected hours per employee for the period. Default 40."},
            },
        },
    }
]

DETECTION_TOOL_FUNCTIONS = {"detect_issues": detect_issues}
