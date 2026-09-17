"""Tests for app.services.ai.approvals — the only code path that actually executes a
data-changing action, and only after a manager decision. These tests verify the approval flow
goes through real backend validation (Pydantic schemas + task_service), not a raw ORM write:
an invalid approved payload must fail cleanly (FAILED status, no partial change), not crash or
silently apply something invalid.
"""

from datetime import date

import pytest

from app.models.agent_action import AgentAction
from app.models.enums import AgentActionStatus, ProjectStatus, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.task_history import TaskHistory
from app.models.user import User
from app.services.ai import actions, approvals


def _seed(db_session):
    manager = User(name="Manager", email="mgr-approvals@example.com", role=UserRole.MANAGER, department="Management")
    alice = User(name="Alice Approvals", email="alice-approvals@example.com", department="Engineering")
    bob = User(name="Bob Approvals", email="bob-approvals@example.com", department="Engineering")
    db_session.add_all([manager, alice, bob])
    db_session.commit()

    project = Project(name="Approvals Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()

    task = Task(project_id=project.id, assigned_to=alice.id, title="Existing task", status=TaskStatus.NOT_STARTED, estimated_hours=4)
    db_session.add(task)
    db_session.commit()

    return {"manager": manager, "alice": alice, "bob": bob, "project": project, "task": task}


def test_approve_create_task_actually_creates_it(db_session):
    seed = _seed(db_session)
    proposal = actions.create_task(
        db_session, project_id=seed["project"].id, title="Approved task", reason="needed",
        assigned_to=seed["alice"].id, priority="high", estimated_hours=6,
    )
    before_count = db_session.query(Task).count()

    result = approvals.decide_action(db_session, proposal["action_id"], approve=True)

    assert result["status"] == "approved"
    assert db_session.query(Task).count() == before_count + 1
    created = db_session.query(Task).filter_by(title="Approved task").one()
    assert created.assigned_to == seed["alice"].id
    assert created.priority.value == "high"

    record = db_session.get(AgentAction, proposal["action_id"])
    assert record.status == AgentActionStatus.APPROVED
    assert record.approved is True
    assert "Created task" in record.result


def test_reject_create_task_creates_nothing(db_session):
    seed = _seed(db_session)
    proposal = actions.create_task(db_session, project_id=seed["project"].id, title="Rejected task", reason="needed")
    before_count = db_session.query(Task).count()

    result = approvals.decide_action(db_session, proposal["action_id"], approve=False)

    assert result["status"] == "rejected"
    assert db_session.query(Task).count() == before_count

    record = db_session.get(AgentAction, proposal["action_id"])
    assert record.status == AgentActionStatus.REJECTED
    assert record.approved is False


def test_approve_update_task_applies_change_and_logs_task_history(db_session):
    seed = _seed(db_session)
    proposal = actions.update_task(db_session, task_id=seed["task"].id, reason="starting work", status="in_progress")

    result = approvals.decide_action(db_session, proposal["action_id"], approve=True, approved_by=seed["manager"].id)

    assert result["status"] == "approved"
    db_session.refresh(seed["task"])
    assert seed["task"].status.value == "in_progress"

    # task_service.update_task's existing status-change history logging still fires.
    history = db_session.query(TaskHistory).filter_by(task_id=seed["task"].id).all()
    assert len(history) == 1
    assert history[0].new_status.value == "in_progress"
    assert history[0].changed_by == seed["manager"].id


def test_approve_assign_task_reassigns(db_session):
    seed = _seed(db_session)
    proposal = actions.assign_task(db_session, task_id=seed["task"].id, employee_id=seed["bob"].id, reason="balance load")

    result = approvals.decide_action(db_session, proposal["action_id"], approve=True)

    assert result["status"] == "approved"
    db_session.refresh(seed["task"])
    assert seed["task"].assigned_to == seed["bob"].id


def test_approve_change_priority(db_session):
    seed = _seed(db_session)
    proposal = actions.change_priority(db_session, task_id=seed["task"].id, priority="urgent", reason="escalation")

    result = approvals.decide_action(db_session, proposal["action_id"], approve=True)

    assert result["status"] == "approved"
    db_session.refresh(seed["task"])
    assert seed["task"].priority.value == "urgent"


def test_approve_fails_cleanly_when_task_deleted_before_approval(db_session):
    seed = _seed(db_session)
    proposal = actions.update_task(db_session, task_id=seed["task"].id, reason="x", title="New title")

    db_session.delete(seed["task"])
    db_session.commit()

    result = approvals.decide_action(db_session, proposal["action_id"], approve=True)

    assert result["status"] == "failed"
    record = db_session.get(AgentAction, proposal["action_id"])
    assert record.status == AgentActionStatus.FAILED
    assert record.approved is False
    assert "no longer exists" in record.result


def test_approve_fails_cleanly_on_invalid_payload_and_session_still_usable(db_session):
    seed = _seed(db_session)
    # Queue a valid proposal, then corrupt its stored payload to something that fails Pydantic
    # validation (negative estimated_hours) — simulates a payload that should never reach the
    # database, proving backend validation still applies at approval time.
    proposal = actions.create_task(db_session, project_id=seed["project"].id, title="Bad task", reason="x")
    record = db_session.get(AgentAction, proposal["action_id"])
    import json

    payload = json.loads(record.payload)
    payload["estimated_hours"] = -5
    record.payload = json.dumps(payload)
    db_session.commit()

    result = approvals.decide_action(db_session, proposal["action_id"], approve=True)

    assert result["status"] == "failed"
    assert db_session.query(Task).filter_by(title="Bad task").count() == 0

    # The session must still be usable after the failure (rollback handled correctly).
    assert db_session.query(User).count() >= 3


def test_decide_action_missing_action_id(db_session):
    result = approvals.decide_action(db_session, 999999, approve=True)
    assert "error" in result


def test_decide_action_already_decided_is_rejected(db_session):
    seed = _seed(db_session)
    proposal = actions.create_task(db_session, project_id=seed["project"].id, title="Once task", reason="x")
    approvals.decide_action(db_session, proposal["action_id"], approve=True)

    result = approvals.decide_action(db_session, proposal["action_id"], approve=True)
    assert "error" in result
    assert "not pending" in result["error"]


def test_list_pending_actions(db_session):
    seed = _seed(db_session)
    actions.create_task(db_session, project_id=seed["project"].id, title="Pending 1", reason="x")
    actions.create_task(db_session, project_id=seed["project"].id, title="Pending 2", reason="x")
    actions.send_notification(db_session, employee_id=seed["alice"].id, message="hi", reason="x")  # auto-executed, not pending

    pending = approvals.list_pending_actions(db_session)

    assert len(pending) == 2
    assert all(a.status == AgentActionStatus.PENDING for a in pending)


def test_list_actions_filters_by_status(db_session):
    seed = _seed(db_session)
    actions.send_notification(db_session, employee_id=seed["alice"].id, message="hi", reason="x")
    actions.create_task(db_session, project_id=seed["project"].id, title="Still pending", reason="x")

    auto_approved = approvals.list_actions(db_session, status=AgentActionStatus.AUTO_APPROVED)
    pending = approvals.list_actions(db_session, status=AgentActionStatus.PENDING)

    assert len(auto_approved) == 1
    assert len(pending) == 1
