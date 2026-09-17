"""Step 8 of the Phase 10 workflow: "generate management summary." Assembles the plain-dict
report payload (JSON-serialized into `DailyManagerReport.summary_json`) from everything the
earlier steps already computed — this module performs no detection or arithmetic of its own,
only shaping/labeling, consistent with every other "tool" layer in this codebase.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import TaskStatus
from app.models.task import Task
from app.services.analytics.dashboard_results import ManagerDashboardResult
from app.services.daily_manager.change_tracking import SignificantChange
from app.services.daily_manager.snapshot import IssueFinding

_RECOMMENDATION_PREFIX = {
    "overloaded_employee": "Review workload:",
    "underutilized_employee": "Consider reassigning work:",
    "workload_imbalance": "Rebalance workload:",
    "approaching_deadline": "Follow up:",
    "delayed_task": "Follow up:",
    "performance_drop": "Check in:",
    "recurring_delay_cause": "Address root cause:",
    "quality_issue": "Review quality:",
    "project_risk": "Escalate:",
}

_ACTIONABLE_FOR_RECOMMENDATIONS = frozenset({"new", "escalated"})


def _completed_today(db: Session, as_of: date) -> list[dict[str, Any]]:
    stmt = select(Task).where(Task.status == TaskStatus.COMPLETED, Task.completed_date == as_of)
    tasks = list(db.scalars(stmt))
    return [
        {
            "task_id": t.id,
            "title": t.title,
            "project": t.project.name if t.project else None,
            "assignee": t.assignee.name if t.assignee else None,
            "quality_score": float(t.quality_score) if t.quality_score is not None else None,
        }
        for t in tasks
    ]


def _recommended_actions(changes: list[SignificantChange]) -> list[str]:
    return [
        f"{_RECOMMENDATION_PREFIX.get(c.issue_type, 'Review:')} {c.label}"
        for c in changes
        if c.change_type in _ACTIONABLE_FOR_RECOMMENDATIONS
    ]


def build_report_data(
    db: Session,
    as_of: date,
    dashboard_result: ManagerDashboardResult,
    findings: list[IssueFinding],
    changes: list[SignificantChange],
    daily_updates_count: int,
    actions_taken: list[dict[str, Any]],
) -> dict[str, Any]:
    by_type: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        by_type.setdefault(f.issue_type, []).append(f.detail)

    workload_problems = (
        [{**d, "issue": "overloaded"} for d in by_type.get("overloaded_employee", [])]
        + [{**d, "issue": "underutilized"} for d in by_type.get("underutilized_employee", [])]
        + [{**d, "issue": "imbalance"} for d in by_type.get("workload_imbalance", [])]
    )

    major_changes = [
        {
            "issue_type": c.issue_type,
            "target_key": c.target_key,
            "change_type": c.change_type,
            "severity": c.severity,
            "previous_severity": c.previous_severity,
            "label": c.label,
        }
        for c in changes
    ]

    action_required = len(changes) > 0

    return {
        "run_date": str(as_of),
        "team_efficiency": dashboard_result.summary.overall_team_efficiency,
        "team_size": dashboard_result.summary.team_size,
        "daily_updates_collected": daily_updates_count,
        "major_changes": major_changes,
        "completed_work": _completed_today(db, as_of),
        "delayed_work": by_type.get("delayed_task", []),
        "at_risk_deadlines": by_type.get("approaching_deadline", []),
        "workload_problems": workload_problems,
        "quality_issues": by_type.get("quality_issue", []),
        "project_risks": by_type.get("project_risk", []),
        "recurring_delay_causes": by_type.get("recurring_delay_cause", []),
        "performance_drops": by_type.get("performance_drop", []),
        "recommended_actions": _recommended_actions(changes),
        "actions_taken": actions_taken,
        "action_required": action_required,
    }
