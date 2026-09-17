"""Approve or reject a PENDING AgentAction (Phase 7).

This is where a manager's decision actually takes effect. Approving an action executes it
through the **exact same** Pydantic schemas and service functions the CRUD API uses
(`TaskCreate`/`TaskUpdate` via `task_service.create_task`/`update_task`) — never a raw ORM
write — so backend validation (field constraints, `CHECK` constraints, foreign keys) applies
identically to an agent-proposed change and a human-typed one. If the payload no longer validates
(e.g. the referenced task or employee was deleted after the action was proposed but before it
was approved), the action is marked FAILED with the validation error as its `result`, and
nothing partial is applied.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agent_action import AgentAction
from app.models.enums import AgentActionStatus
from app.schemas.task import TaskCreate, TaskUpdate
from app.services import task_service


def list_pending_actions(db: Session, limit: int = 100) -> list[AgentAction]:
    stmt = (
        select(AgentAction)
        .where(AgentAction.status == AgentActionStatus.PENDING)
        .order_by(AgentAction.timestamp.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def list_actions(db: Session, status: AgentActionStatus | None = None, limit: int = 100) -> list[AgentAction]:
    stmt = select(AgentAction).order_by(AgentAction.timestamp.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(AgentAction.status == status)
    return list(db.scalars(stmt))


def _execute_payload(db: Session, action: str, payload: dict[str, Any], approved_by: int | None) -> str:
    """Apply a pending action's payload via real backend validation. Returns a human-readable
    success summary. Raises ValueError/ValidationError/IntegrityError on failure — the caller
    (`decide_action`) catches these and records them as the action's failure result.
    """
    if action == "create_task":
        data = TaskCreate(**payload)
        task = task_service.create_task(db, data)
        return f"Created task #{task.id}: {task.title!r}."

    if action == "update_task":
        payload = dict(payload)
        task_id = payload.pop("task_id")
        task = task_service.get_task(db, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} no longer exists.")
        if approved_by is not None:
            payload["changed_by"] = approved_by
        data = TaskUpdate(**payload)
        task_service.update_task(db, task, data)
        return f"Updated task #{task_id}."

    if action == "assign_task":
        task_id = payload["task_id"]
        task = task_service.get_task(db, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} no longer exists.")
        data = TaskUpdate(assigned_to=payload["assigned_to"], changed_by=approved_by)
        task_service.update_task(db, task, data)
        return f"Reassigned task #{task_id} to employee #{payload['assigned_to']}."

    if action == "change_priority":
        task_id = payload["task_id"]
        task = task_service.get_task(db, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} no longer exists.")
        data = TaskUpdate(priority=payload["priority"], changed_by=approved_by)
        task_service.update_task(db, task, data)
        return f"Changed priority of task #{task_id} to {payload['priority']}."

    raise ValueError(f"{action!r} is not an approval-required action that can be executed.")


def decide_action(db: Session, action_id: int, approve: bool, approved_by: int | None = None) -> dict[str, Any]:
    """Approve (execute) or reject a pending action. Returns a plain dict describing the
    outcome; never raises for an expected business condition (missing action, wrong state,
    execution failure) — those become `{"error": ...}` results, consistent with every other
    tool in this package.
    """
    record = db.get(AgentAction, action_id)
    if record is None:
        return {"error": f"No action with id {action_id}."}
    if record.status != AgentActionStatus.PENDING:
        return {"error": f"Action {action_id} is not pending (status={record.status.value})."}

    if not approve:
        record.status = AgentActionStatus.REJECTED
        record.approved = False
        record.result = "Rejected by manager."
        db.commit()
        db.refresh(record)
        return {"action_id": action_id, "status": record.status.value, "result": record.result}

    payload = json.loads(record.payload) if record.payload else {}
    try:
        summary = _execute_payload(db, record.action, payload, approved_by)
    except (ValidationError, IntegrityError, ValueError) as exc:
        db.rollback()
        record = db.get(AgentAction, action_id)
        record.status = AgentActionStatus.FAILED
        record.approved = False
        record.result = f"Execution failed: {exc}"
        db.commit()
        db.refresh(record)
        return {"action_id": action_id, "status": record.status.value, "result": record.result}

    record.status = AgentActionStatus.APPROVED
    record.approved = True
    record.result = summary
    db.commit()
    db.refresh(record)
    return {"action_id": action_id, "status": record.status.value, "result": record.result}
