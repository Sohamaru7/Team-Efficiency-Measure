"""Step 3 of the Phase 10 workflow: "identify significant changes." Diffs today's issue
snapshot against `DailyManagerIssueState` (one row per issue_type+target_key, upserted here) and
returns only what's actually new information — a brand-new issue, one that got worse, one that
got better, or one that's now resolved. An issue sitting at the exact same severity as last time
it was reported produces **no** entry here, even though it's still fully visible in the report's
raw category sections (workload_problems, at_risk_deadlines, etc.) — this is what implements
"the agent should not repeatedly alert managers about the same issue unless its severity
changes" without hiding the issue from the report entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.daily_manager import DailyManagerIssueState
from app.services.daily_manager.constants import SEVERITY_ORDER
from app.services.daily_manager.snapshot import IssueFinding


@dataclass
class SignificantChange:
    issue_type: str
    target_key: str
    change_type: str  # "new" | "escalated" | "de-escalated" | "resolved"
    severity: str
    previous_severity: str | None
    label: str
    detail: dict[str, Any]


def diff_and_update_issue_state(db: Session, findings: list[IssueFinding], as_of: date) -> list[SignificantChange]:
    all_existing = {(row.issue_type, row.target_key): row for row in db.scalars(select(DailyManagerIssueState))}
    changes: list[SignificantChange] = []
    seen_keys: set[tuple[str, str]] = set()

    for finding in findings:
        key = (finding.issue_type, finding.target_key)
        seen_keys.add(key)
        row = all_existing.get(key)

        if row is None:
            db.add(
                DailyManagerIssueState(
                    issue_type=finding.issue_type, target_key=finding.target_key, severity=finding.severity,
                    first_detected_at=as_of, last_seen_at=as_of, last_reported_severity=finding.severity, resolved_at=None,
                )
            )
            changes.append(SignificantChange(finding.issue_type, finding.target_key, "new", finding.severity, None, finding.label, finding.detail))
            continue

        if row.resolved_at is not None:
            # Previously resolved, now recurring — treat as a fresh issue.
            row.resolved_at = None
            row.first_detected_at = as_of
            row.last_seen_at = as_of
            row.severity = finding.severity
            row.last_reported_severity = finding.severity
            changes.append(SignificantChange(finding.issue_type, finding.target_key, "new", finding.severity, None, finding.label, finding.detail))
            continue

        row.last_seen_at = as_of
        row.severity = finding.severity
        old_rank = SEVERITY_ORDER[row.last_reported_severity]
        new_rank = SEVERITY_ORDER[finding.severity]
        if new_rank > old_rank:
            changes.append(
                SignificantChange(finding.issue_type, finding.target_key, "escalated", finding.severity, row.last_reported_severity, finding.label, finding.detail)
            )
            row.last_reported_severity = finding.severity
        elif new_rank < old_rank:
            changes.append(
                SignificantChange(finding.issue_type, finding.target_key, "de-escalated", finding.severity, row.last_reported_severity, finding.label, finding.detail)
            )
            row.last_reported_severity = finding.severity
        # else: unchanged severity -> no SignificantChange, last_reported_severity untouched.

    for (issue_type, target_key), row in all_existing.items():
        if (issue_type, target_key) in seen_keys or row.resolved_at is not None:
            continue
        row.resolved_at = as_of
        changes.append(
            SignificantChange(
                issue_type, target_key, "resolved", "resolved", row.last_reported_severity,
                f"Previously reported issue ({issue_type} — {target_key}) is no longer present", {},
            )
        )

    db.commit()
    return changes
