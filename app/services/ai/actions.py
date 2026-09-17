"""Write-capable tools for the manager agent (Phase 7).

Two risk tiers, per the brief:

- **Auto-execute** (`send_notification`, `generate_report`): these don't change any task,
  project, or user row — a notification is a logged, auditable message, and a report is a
  read-only aggregation — so they run immediately inside the tool call and log a single
  `AgentAction` with `status=AUTO_APPROVED`.
- **Requires approval** (`create_task`, `update_task`, `assign_task`, `change_priority`): these
  change task data or an employee's assignment/workload, so the tool call does **not** perform
  the change. It validates that the referenced project/task/employee exists (a real read, not
  a guess), then records the proposed change as a `PENDING` `AgentAction` with the full payload
  needed to execute it later, and returns that pending state to the model — never a claim that
  the change happened. `approvals.py` executes (or rejects) it once a manager decides.

**Backend validation is never bypassed.** Every action that actually mutates data — whether
executed here (none do, for approval-required actions) or later in `approvals.py` — goes through
the exact same Pydantic schemas (`TaskCreate`/`TaskUpdate`) and service functions
(`task_service.create_task`/`update_task`) the CRUD API itself uses. There is no direct ORM
write anywhere in this module.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.agent_action import AgentAction
from app.models.enums import AgentActionStatus
from app.services import project_service, task_service, user_service
from app.services.ai import detection
from app.services.ai.tools import (
    get_at_risk_tasks,
    get_overdue_tasks,
    get_quality_metrics,
    get_recent_delays,
    get_team_metrics,
    get_workload,
)

AGENT_TYPE = "manager_agent"

# Tool names in each risk tier — the assistant loop (assistant.py) uses these to decide whether
# a tool call needs its own generic audit log entry (read tools do) or has already logged itself
# with richer status/payload/result fields (every tool in this module does).
APPROVAL_REQUIRED_TOOLS = {"create_task", "update_task", "assign_task", "change_priority"}
AUTO_EXECUTE_TOOLS = {"send_notification", "generate_report"}
ACTION_TOOL_NAMES = APPROVAL_REQUIRED_TOOLS | AUTO_EXECUTE_TOOLS


def _queue_for_approval(
    db: Session, action: str, target: str, reason: str, payload: dict[str, Any], agent_type: str = AGENT_TYPE
) -> dict[str, Any]:
    record = AgentAction(
        agent_type=agent_type,
        action=action,
        target=target,
        reason=reason,
        payload=json.dumps(payload, default=str),
        status=AgentActionStatus.PENDING,
        approved=False,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "status": "pending_approval",
        "action_id": record.id,
        "message": f"This action changes task/employee data, so it requires manager approval. Queued as pending action #{record.id}.",
    }


def _log_auto_executed(db: Session, action: str, target: str, reason: str, result: Any, agent_type: str = AGENT_TYPE) -> AgentAction:
    record = AgentAction(
        agent_type=agent_type,
        action=action,
        target=target,
        reason=reason,
        result=result if isinstance(result, str) else json.dumps(result, default=str),
        status=AgentActionStatus.AUTO_APPROVED,
        approved=True,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


# ------------------------------------------------------------------------- approval-required ----


def create_task(
    db: Session,
    project_id: int,
    title: str,
    reason: str,
    assigned_to: int | None = None,
    description: str | None = None,
    priority: str = "medium",
    estimated_hours: float | None = None,
    start_date: str | None = None,
    deadline: str | None = None,
    agent_type: str = AGENT_TYPE,
) -> dict[str, Any]:
    """Propose creating a new task. Requires manager approval before it's actually created."""
    if project_service.get_project(db, project_id) is None:
        return {"error": f"No project with id {project_id}."}
    if assigned_to is not None and user_service.get_user(db, assigned_to) is None:
        return {"error": f"No employee with id {assigned_to}."}

    payload = {
        "project_id": project_id,
        "title": title,
        "assigned_to": assigned_to,
        "description": description,
        "priority": priority,
        "estimated_hours": estimated_hours,
        "start_date": start_date,
        "deadline": deadline,
    }
    return _queue_for_approval(db, "create_task", f"project:{project_id}", reason, payload, agent_type=agent_type)


def update_task(
    db: Session,
    task_id: int,
    reason: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    estimated_hours: float | None = None,
    actual_hours: float | None = None,
    start_date: str | None = None,
    deadline: str | None = None,
    completed_date: str | None = None,
    quality_score: float | None = None,
    delay_reason: str | None = None,
    agent_type: str = AGENT_TYPE,
) -> dict[str, Any]:
    """Propose updating a task's fields. Requires manager approval before anything changes."""
    if task_service.get_task(db, task_id) is None:
        return {"error": f"No task with id {task_id}."}

    payload = {
        k: v
        for k, v in {
            "title": title,
            "description": description,
            "status": status,
            "priority": priority,
            "estimated_hours": estimated_hours,
            "actual_hours": actual_hours,
            "start_date": start_date,
            "deadline": deadline,
            "completed_date": completed_date,
            "quality_score": quality_score,
            "delay_reason": delay_reason,
        }.items()
        if v is not None
    }
    if not payload:
        return {"error": "No fields to update were provided."}
    payload["task_id"] = task_id
    return _queue_for_approval(db, "update_task", f"task:{task_id}", reason, payload, agent_type=agent_type)


def assign_task(db: Session, task_id: int, employee_id: int, reason: str, agent_type: str = AGENT_TYPE) -> dict[str, Any]:
    """Propose reassigning a task to a different employee. Requires manager approval."""
    if task_service.get_task(db, task_id) is None:
        return {"error": f"No task with id {task_id}."}
    if user_service.get_user(db, employee_id) is None:
        return {"error": f"No employee with id {employee_id}."}

    payload = {"task_id": task_id, "assigned_to": employee_id}
    return _queue_for_approval(db, "assign_task", f"task:{task_id}", reason, payload, agent_type=agent_type)


def change_priority(db: Session, task_id: int, priority: str, reason: str, agent_type: str = AGENT_TYPE) -> dict[str, Any]:
    """Propose changing a task's priority. Requires manager approval."""
    if task_service.get_task(db, task_id) is None:
        return {"error": f"No task with id {task_id}."}

    payload = {"task_id": task_id, "priority": priority}
    return _queue_for_approval(db, "change_priority", f"task:{task_id}", reason, payload, agent_type=agent_type)


# ------------------------------------------------------------------------------ auto-execute ----


def send_notification(
    db: Session, employee_id: int, message: str, reason: str, agent_type: str = AGENT_TYPE
) -> dict[str, Any]:
    """Send a reminder/notification to an employee. Low-risk (no task/project data changes),
    so this executes and logs immediately — no approval needed.

    There is no delivery channel yet (no email/SMS/in-app inbox in this system) — the
    notification is recorded as an auditable `AgentAction`, not delivered anywhere a user would
    currently see it. See the README for this documented limitation.
    """
    user = user_service.get_user(db, employee_id)
    if user is None:
        return {"error": f"No employee with id {employee_id}."}

    record = _log_auto_executed(
        db,
        "send_notification",
        f"employee:{employee_id}",
        reason,
        f"Notification recorded for {user.name}: {message}",
        agent_type=agent_type,
    )
    return {"status": "sent", "action_id": record.id, "recipient": user.name, "message": message}


def generate_report(
    db: Session,
    report_type: str,
    reason: str,
    department: str | None = None,
    agent_type: str = AGENT_TYPE,
) -> dict[str, Any]:
    """Generate a report by aggregating existing read-only analytics (no new metrics are
    computed here — every number is a direct pass-through of an already-tested tool's output).
    Low-risk (read-only), so this executes and logs immediately.

    report_type: one of "team_summary", "workload", "at_risk", "overdue", "delays", "quality",
    "issues" (issues = detect_issues, everything at once).
    """
    generators = {
        "team_summary": lambda: get_team_metrics(db, department=department),
        "workload": lambda: get_workload(db, department=department),
        "at_risk": lambda: get_at_risk_tasks(db, department=department),
        "overdue": lambda: get_overdue_tasks(db, department=department),
        "delays": lambda: get_recent_delays(db, department=department),
        "quality": lambda: get_quality_metrics(db, department=department),
        "issues": lambda: detection.detect_issues(db, department=department),
    }
    generator = generators.get(report_type)
    if generator is None:
        return {"error": f"Unknown report_type {report_type!r}. Choose one of: {sorted(generators)}."}

    report = generator()
    record = _log_auto_executed(db, "generate_report", f"report:{report_type}", reason, report, agent_type=agent_type)
    return {"status": "generated", "action_id": record.id, "report_type": report_type, "report": report}


# --------------------------------------------------------------------------- tool schemas ----

ACTION_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "create_task",
        "description": (
            "Propose creating a new task in a project. This changes project/employee data, so "
            "it requires manager approval — it is queued as a pending action, not created "
            "immediately. Always explain the reason."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "title": {"type": "string"},
                "reason": {"type": "string", "description": "Why this task should be created."},
                "assigned_to": {"type": "integer", "description": "Employee id to assign the task to. Omit to leave unassigned."},
                "description": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                "estimated_hours": {"type": "number"},
                "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD."},
                "deadline": {"type": "string", "description": "ISO date YYYY-MM-DD."},
            },
            "required": ["project_id", "title", "reason"],
        },
    },
    {
        "name": "update_task",
        "description": (
            "Propose updating one or more fields on an existing task (status, hours, dates, "
            "quality score, delay reason, etc.). Requires manager approval — queued as a "
            "pending action. Always explain the reason."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "reason": {"type": "string", "description": "Why this change is being proposed."},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "status": {"type": "string", "enum": ["not_started", "in_progress", "blocked", "completed", "cancelled"]},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                "estimated_hours": {"type": "number"},
                "actual_hours": {"type": "number"},
                "start_date": {"type": "string"},
                "deadline": {"type": "string"},
                "completed_date": {"type": "string"},
                "quality_score": {"type": "number"},
                "delay_reason": {"type": "string"},
            },
            "required": ["task_id", "reason"],
        },
    },
    {
        "name": "assign_task",
        "description": (
            "Propose reassigning a task to a different employee. Requires manager approval — "
            "queued as a pending action. Always explain the reason (e.g. to fix a workload "
            "imbalance)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "employee_id": {"type": "integer", "description": "The employee to reassign the task to."},
                "reason": {"type": "string"},
            },
            "required": ["task_id", "employee_id", "reason"],
        },
    },
    {
        "name": "change_priority",
        "description": (
            "Propose changing a task's priority. Requires manager approval — queued as a "
            "pending action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                "reason": {"type": "string"},
            },
            "required": ["task_id", "priority", "reason"],
        },
    },
    {
        "name": "send_notification",
        "description": (
            "Send a reminder/notification to an employee. Low-risk — executes immediately, no "
            "approval needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "integer"},
                "message": {"type": "string"},
                "reason": {"type": "string", "description": "Why this notification is being sent."},
            },
            "required": ["employee_id", "message", "reason"],
        },
    },
    {
        "name": "generate_report",
        "description": (
            "Generate a report by aggregating existing analytics — no new metrics are computed. "
            "Low-risk — executes immediately, no approval needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": ["team_summary", "workload", "at_risk", "overdue", "delays", "quality", "issues"],
                },
                "department": {"type": "string"},
                "reason": {"type": "string", "description": "Why this report is being generated."},
            },
            "required": ["report_type", "reason"],
        },
    },
]

ACTION_TOOL_FUNCTIONS = {
    "create_task": create_task,
    "update_task": update_task,
    "assign_task": assign_task,
    "change_priority": change_priority,
    "send_notification": send_notification,
    "generate_report": generate_report,
}
