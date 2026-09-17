"""Builds today's full issue snapshot: every finding from `app.services.ai.detection`'s
`detect_issues` (Phase 7, unchanged) plus the two Phase 10 additions (`detect_quality_issues`,
`detect_project_risks`), each normalized into one `IssueFinding` shape with a deterministic
severity attached. This is step 4-7 of the Phase 10 workflow ("detect workload issues," "detect
deadline risks," "detect recurring delays," "analyze project progress") — all of it is
detection/composition over already-tested functions; nothing here computes a new metric.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.services.ai import detection
from app.services.daily_manager import constants as c


@dataclass
class IssueFinding:
    issue_type: str
    target_key: str
    severity: str
    label: str
    detail: dict[str, Any]


def _overloaded_severity(pct: float) -> str:
    if pct > c.OVERLOAD_HIGH_PCT:
        return "high"
    if pct > c.OVERLOAD_MEDIUM_PCT:
        return "medium"
    return "low"


def _underutilized_severity(pct: float) -> str:
    if pct < c.UNDERUTILIZED_HIGH_MAX_PCT:
        return "high"
    if pct < c.UNDERUTILIZED_MEDIUM_MAX_PCT:
        return "medium"
    return "low"


def _imbalance_severity(spread: float) -> str:
    if spread > c.IMBALANCE_HIGH_SPREAD:
        return "high"
    if spread > c.IMBALANCE_MEDIUM_SPREAD:
        return "medium"
    return "low"


def _deadline_risk_severity(risk: str) -> str:
    # get_at_risk_tasks only ever returns HIGH/MEDIUM (OVERDUE surfaces via delayed_tasks below).
    return "high" if risk == "high" else "medium"


def _delay_severity(delay_days: int | None) -> str:
    days = delay_days or 0
    if days > c.DELAY_HIGH_DAYS:
        return "high"
    if days > c.DELAY_MEDIUM_DAYS:
        return "medium"
    return "low"


def _performance_drop_severity(drop_pct: float) -> str:
    if drop_pct > c.PERFORMANCE_DROP_HIGH_PCT:
        return "high"
    if drop_pct > c.PERFORMANCE_DROP_MEDIUM_PCT:
        return "medium"
    return "low"


def _recurring_severity(occurrences: int) -> str:
    if occurrences >= c.RECURRING_HIGH_COUNT:
        return "high"
    if occurrences >= c.RECURRING_MEDIUM_COUNT:
        return "medium"
    return "low"


def _quality_severity(score: float) -> str:
    if score < c.QUALITY_HIGH_MAX_SCORE:
        return "high"
    if score < c.QUALITY_MEDIUM_MAX_SCORE:
        return "medium"
    return "low"


def _project_risk_severity(days_left: int) -> str:
    if days_left <= c.PROJECT_RISK_HIGH_DAYS:
        return "high"
    if days_left <= c.PROJECT_RISK_MEDIUM_DAYS:
        return "medium"
    return "low"


def build_issue_snapshot(db: Session, as_of: date) -> list[IssueFinding]:
    as_of_str = str(as_of)
    issues = detection.detect_issues(db, as_of=as_of_str)
    findings: list[IssueFinding] = []

    for e in issues["overloaded_employees"]:
        findings.append(
            IssueFinding(
                "overloaded_employee", f"employee:{e['employee_id']}", _overloaded_severity(e["utilization_pct"]),
                f"{e['name']} is overloaded at {e['utilization_pct']}% utilization", e,
            )
        )
    for e in issues["underutilized_employees"]:
        findings.append(
            IssueFinding(
                "underutilized_employee", f"employee:{e['employee_id']}", _underutilized_severity(e["utilization_pct"]),
                f"{e['name']} is underutilized at {e['utilization_pct']}% utilization", e,
            )
        )
    imbalance = issues["workload_imbalance"]
    if imbalance:
        findings.append(
            IssueFinding(
                "workload_imbalance", "team", _imbalance_severity(imbalance["spread_pct"]),
                f"Workload imbalance of {imbalance['spread_pct']} points between "
                f"{imbalance['most_loaded']['name']} and {imbalance['least_loaded']['name']}",
                imbalance,
            )
        )
    for t in issues["approaching_deadlines"]:
        findings.append(
            IssueFinding(
                "approaching_deadline", f"task:{t['task_id']}", _deadline_risk_severity(t["risk"]),
                f"Task '{t['title']}' is at {t['risk']} risk of missing its deadline ({t['days_left']} day(s) left)", t,
            )
        )
    for t in issues["delayed_tasks"]:
        findings.append(
            IssueFinding(
                "delayed_task", f"task:{t['task_id']}", _delay_severity(t["delay_days"]),
                f"Task '{t['title']}' is delayed by {t['delay_days']} day(s)", t,
            )
        )
    for p in issues["performance_drops"]:
        findings.append(
            IssueFinding(
                "performance_drop", f"employee:{p['employee_id']}", _performance_drop_severity(p["drop_pct"]),
                f"{p['name']}'s completion ratio dropped {p['drop_pct']} points", p,
            )
        )
    for r in issues["recurring_delay_causes"]:
        findings.append(
            IssueFinding(
                "recurring_delay_cause", f"reason:{r['reason'][:80]}", _recurring_severity(r["occurrences"]),
                f"Recurring delay cause: '{r['reason']}' ({r['occurrences']} occurrences)", r,
            )
        )
    for q in detection.detect_quality_issues(db, as_of=as_of_str):
        findings.append(
            IssueFinding(
                "quality_issue", f"task:{q['task_id']}", _quality_severity(q["quality_score"]),
                f"Task '{q['title']}' completed by {q['name']} with a low quality score ({q['quality_score']})", q,
            )
        )
    for pr in detection.detect_project_risks(db, as_of=as_of_str):
        findings.append(
            IssueFinding(
                "project_risk", f"project:{pr['project_id']}", _project_risk_severity(pr["days_left"]),
                f"Project '{pr['name']}' is at {pr['progress_pct']}% progress with {pr['days_left']} day(s) to its deadline",
                pr,
            )
        )

    return findings
