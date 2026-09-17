"""Unit tests for app.services.ai.actions — the six write-capable tools. Verifies the risk
split from the brief: the four data-changing tools only ever queue a PENDING AgentAction (never
touch tasks/projects/users), and the two low-risk tools execute + log immediately.
"""

from datetime import date

import pytest

from app.models.agent_action import AgentAction
from app.models.enums import AgentActionStatus, ProjectStatus, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.ai import actions


def _seed(db_session):
    manager = User(name="Manager", email="mgr-actions@example.com", role=UserRole.MANAGER, department="Management")
    alice = User(name="Alice Actions", email="alice-actions@example.com", department="Engineering")
    bob = User(name="Bob Actions", email="bob-actions@example.com", department="Engineering")
    db_session.add_all([manager, alice, bob])
    db_session.commit()

    project = Project(name="Actions Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()

    task = Task(project_id=project.id, assigned_to=alice.id, title="Existing task", status=TaskStatus.NOT_STARTED, estimated_hours=4)
    db_session.add(task)
    db_session.commit()

    return {"manager": manager, "alice": alice, "bob": bob, "project": project, "task": task}


# ------------------------------------------------------------------------- approval-required ----


def test_create_task_queues_pending_not_created(db_session):
    seed = _seed(db_session)
    before_count = db_session.query(Task).count()

    result = actions.create_task(
        db_session, project_id=seed["project"].id, title="New task", reason="needed for launch",
        assigned_to=seed["alice"].id, priority="high",
    )

    assert result["status"] == "pending_approval"
    assert db_session.query(Task).count() == before_count  # nothing created yet

    record = db_session.get(AgentAction, result["action_id"])
    assert record.status == AgentActionStatus.PENDING
    assert record.approved is False
    assert record.action == "create_task"
    assert record.reason == "needed for launch"
    assert "project" in record.target


def test_create_task_rejects_missing_project(db_session):
    result = actions.create_task(db_session, project_id=999999, title="X", reason="why")
    assert "error" in result


def test_create_task_rejects_missing_assignee(db_session):
    seed = _seed(db_session)
    result = actions.create_task(db_session, project_id=seed["project"].id, title="X", reason="why", assigned_to=999999)
    assert "error" in result


def test_update_task_queues_pending_not_applied(db_session):
    seed = _seed(db_session)
    original_title = seed["task"].title

    result = actions.update_task(db_session, task_id=seed["task"].id, reason="scope clarified", title="Renamed task")

    assert result["status"] == "pending_approval"
    db_session.refresh(seed["task"])
    assert seed["task"].title == original_title  # unchanged


def test_update_task_missing_task(db_session):
    result = actions.update_task(db_session, task_id=999999, reason="x", title="Y")
    assert "error" in result


def test_update_task_no_fields_is_an_error(db_session):
    seed = _seed(db_session)
    result = actions.update_task(db_session, task_id=seed["task"].id, reason="x")
    assert "error" in result


def test_assign_task_queues_pending(db_session):
    seed = _seed(db_session)
    result = actions.assign_task(db_session, task_id=seed["task"].id, employee_id=seed["bob"].id, reason="balance load")
    assert result["status"] == "pending_approval"
    db_session.refresh(seed["task"])
    assert seed["task"].assigned_to == seed["alice"].id  # unchanged until approved


def test_assign_task_missing_employee(db_session):
    seed = _seed(db_session)
    result = actions.assign_task(db_session, task_id=seed["task"].id, employee_id=999999, reason="x")
    assert "error" in result


def test_change_priority_queues_pending(db_session):
    seed = _seed(db_session)
    result = actions.change_priority(db_session, task_id=seed["task"].id, priority="urgent", reason="client escalation")
    assert result["status"] == "pending_approval"
    db_session.refresh(seed["task"])
    assert seed["task"].priority.value != "urgent"  # unchanged until approved


# ------------------------------------------------------------------------------ auto-execute ----


def test_send_notification_executes_and_logs_immediately(db_session):
    seed = _seed(db_session)
    result = actions.send_notification(db_session, employee_id=seed["alice"].id, message="Please update your task", reason="overdue reminder")

    assert result["status"] == "sent"
    record = db_session.get(AgentAction, result["action_id"])
    assert record.status == AgentActionStatus.AUTO_APPROVED
    assert record.approved is True
    assert "Please update your task" in record.result


def test_send_notification_missing_employee(db_session):
    result = actions.send_notification(db_session, employee_id=999999, message="hi", reason="x")
    assert "error" in result


def test_generate_report_executes_and_logs_immediately(db_session):
    seed = _seed(db_session)
    result = actions.generate_report(db_session, report_type="workload", reason="weekly check-in", department="Engineering")

    assert result["status"] == "generated"
    assert isinstance(result["report"], list)  # get_workload department view returns a list
    record = db_session.get(AgentAction, result["action_id"])
    assert record.status == AgentActionStatus.AUTO_APPROVED
    assert record.result is not None


def test_generate_report_unknown_type(db_session):
    result = actions.generate_report(db_session, report_type="not_a_real_type", reason="x")
    assert "error" in result


def test_action_tool_names_partition_matches_brief():
    # create_task/update_task/assign_task/change_priority require approval;
    # send_notification/generate_report auto-execute — exactly as specified.
    assert actions.APPROVAL_REQUIRED_TOOLS == {"create_task", "update_task", "assign_task", "change_priority"}
    assert actions.AUTO_EXECUTE_TOOLS == {"send_notification", "generate_report"}
    assert actions.ACTION_TOOL_NAMES == actions.APPROVAL_REQUIRED_TOOLS | actions.AUTO_EXECUTE_TOOLS
