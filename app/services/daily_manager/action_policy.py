"""Steps 9-10 of the Phase 10 workflow: "decide whether action is required" and "execute only
permitted actions."

Only NEW or ESCALATED significant changes ever trigger an autonomous action — a resolved issue
needs no action, and a de-escalated one is good news, not a new problem. Every action goes
through `app.services.ai.actions` (Phase 7) — the exact same validated, audited functions the
chat assistant uses — tagged `agent_type="daily_manager"` so the audit trail can distinguish
autonomous actions from ones a manager asked for in chat. Two tools only, both already
risk-classified by Phase 7 and never touched here:

- `send_notification` (auto-executes — a logged message, not a data change) for a newly/more
  overloaded employee.
- `assign_task` (APPROVAL-REQUIRED in actions.py — only ever queues a PENDING AgentAction) for a
  newly/more severe workload imbalance, proposing to move the most-loaded person's single most
  at-risk active task to the least-loaded person. This is a deterministic selection (the most
  urgent real task already found by `get_at_risk_tasks`), not a guess — and it never takes
  effect without a manager clicking Approve, satisfying "keep human approval for... major task
  reassignment."

Nothing else is ever called from here — no `create_task`/`update_task`/`change_priority`, no
delete of any kind, and there is no tool anywhere in this system for performance penalties,
disciplinary decisions, or employee-evaluation changes (see README "Human approval boundary").
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.ai import actions, tools
from app.services.daily_manager.change_tracking import SignificantChange

AGENT_TYPE = "daily_manager"

ACTIONABLE_CHANGE_TYPES = frozenset({"new", "escalated"})


def decide_and_execute_actions(db: Session, changes: list[SignificantChange]) -> list[dict[str, Any]]:
    actions_taken: list[dict[str, Any]] = []

    for change in changes:
        if change.change_type not in ACTIONABLE_CHANGE_TYPES:
            continue

        if change.issue_type == "overloaded_employee":
            outcome = _notify_overloaded_employee(db, change)
        elif change.issue_type == "workload_imbalance":
            outcome = _propose_imbalance_reassignment(db, change)
        else:
            outcome = None

        if outcome is not None:
            actions_taken.append(outcome)

    return actions_taken


def _notify_overloaded_employee(db: Session, change: SignificantChange) -> dict[str, Any] | None:
    employee_id = int(change.target_key.split(":", 1)[1])
    pct = change.detail.get("utilization_pct")
    result = actions.send_notification(
        db,
        employee_id=employee_id,
        message=f"Your workload utilization is {pct}%, above the healthy range. Let your manager know if you need support.",
        reason=f"Autonomous daily check: {change.change_type} overload ({change.severity} severity).",
        agent_type=AGENT_TYPE,
    )
    if "error" in result:
        return {"action": "send_notification", "target": change.target_key, "status": "failed", "detail": result["error"]}
    return {"action": "send_notification", "target": change.target_key, "status": "sent", "action_id": result["action_id"]}


def _propose_imbalance_reassignment(db: Session, change: SignificantChange) -> dict[str, Any] | None:
    most_loaded_id = change.detail["most_loaded"]["employee_id"]
    least_loaded_id = change.detail["least_loaded"]["employee_id"]

    at_risk = tools.get_at_risk_tasks(db, employee_id=most_loaded_id)
    if not at_risk:
        return None

    candidate = sorted(at_risk, key=lambda r: r["days_left"] if r["days_left"] is not None else 999)[0]
    result = actions.assign_task(
        db,
        task_id=candidate["task_id"],
        employee_id=least_loaded_id,
        reason=(
            f"Autonomous daily check: workload imbalance of {change.detail['spread_pct']} points "
            f"({change.severity} severity); task #{candidate['task_id']} is at {candidate['risk']} deadline risk "
            "under the most-loaded employee."
        ),
        agent_type=AGENT_TYPE,
    )
    if "error" in result:
        return {"action": "assign_task", "target": f"task:{candidate['task_id']}", "status": "failed", "detail": result["error"]}
    return {
        "action": "assign_task",
        "target": f"task:{candidate['task_id']}",
        "status": result.get("status", "pending_approval"),
        "action_id": result["action_id"],
    }
