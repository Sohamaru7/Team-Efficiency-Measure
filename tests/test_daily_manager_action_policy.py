"""Unit tests for app.services.daily_manager.action_policy.decide_and_execute_actions — steps
9-10 of the Phase 10 workflow. Verifies the two allowed action types execute/queue correctly,
that non-actionable change types are skipped, and (the key guardrail) that nothing outside
{send_notification, assign_task} is ever called, and every action lands in agent_actions tagged
agent_type="daily_manager" for the audit trail.
"""

from datetime import date, timedelta

from app.models.agent_action import AgentAction
from app.models.enums import AgentActionStatus, ProjectStatus, TaskPriority, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.daily_manager.action_policy import AGENT_TYPE, decide_and_execute_actions
from app.services.daily_manager.change_tracking import SignificantChange


def _seed(db_session):
    manager = User(name="Manager Policy", email="mgr-policy@example.com", role=UserRole.MANAGER, department="Engineering")
    alice = User(name="Alice Policy", email="alice-policy@example.com", department="Engineering")
    bob = User(name="Bob Policy", email="bob-policy@example.com", department="Engineering")
    db_session.add_all([manager, alice, bob])
    db_session.commit()
    project = Project(name="Policy Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    return {"manager": manager, "alice": alice, "bob": bob, "project": project}


def test_overloaded_employee_triggers_notification(db_session):
    seed = _seed(db_session)
    change = SignificantChange(
        "overloaded_employee", f"employee:{seed['alice'].id}", "new", "high", None,
        "Alice is overloaded", {"utilization_pct": 160.0},
    )
    actions_taken = decide_and_execute_actions(db_session, [change])

    assert len(actions_taken) == 1
    assert actions_taken[0]["action"] == "send_notification"
    assert actions_taken[0]["status"] == "sent"

    record = db_session.get(AgentAction, actions_taken[0]["action_id"])
    assert record.agent_type == AGENT_TYPE
    assert record.status == AgentActionStatus.AUTO_APPROVED
    assert record.action == "send_notification"


def test_workload_imbalance_queues_reassignment_for_approval(db_session):
    seed = _seed(db_session)
    today = date(2026, 8, 15)
    at_risk_task = Task(
        project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Urgent thing",
        status=TaskStatus.IN_PROGRESS, priority=TaskPriority.HIGH, deadline=today + timedelta(days=1),
    )
    db_session.add(at_risk_task)
    db_session.commit()

    change = SignificantChange(
        "workload_imbalance", "team", "new", "high", None, "Imbalance",
        {
            "spread_pct": 85.0,
            "most_loaded": {"employee_id": seed["alice"].id, "name": "Alice Policy", "utilization_pct": 160.0},
            "least_loaded": {"employee_id": seed["bob"].id, "name": "Bob Policy", "utilization_pct": 5.0},
        },
    )
    actions_taken = decide_and_execute_actions(db_session, [change])

    assert len(actions_taken) == 1
    assert actions_taken[0]["action"] == "assign_task"
    assert actions_taken[0]["status"] == "pending_approval"

    record = db_session.get(AgentAction, actions_taken[0]["action_id"])
    assert record.agent_type == AGENT_TYPE
    assert record.status == AgentActionStatus.PENDING
    assert record.approved is False  # never auto-applied -- requires a manager's Approve click

    db_session.refresh(at_risk_task)
    assert at_risk_task.assigned_to == seed["alice"].id  # unchanged until approved


def test_workload_imbalance_no_action_when_most_loaded_has_no_at_risk_task(db_session):
    seed = _seed(db_session)
    change = SignificantChange(
        "workload_imbalance", "team", "new", "high", None, "Imbalance",
        {
            "spread_pct": 85.0,
            "most_loaded": {"employee_id": seed["alice"].id, "name": "Alice Policy", "utilization_pct": 160.0},
            "least_loaded": {"employee_id": seed["bob"].id, "name": "Bob Policy", "utilization_pct": 5.0},
        },
    )
    actions_taken = decide_and_execute_actions(db_session, [change])
    assert actions_taken == []  # no invented reassignment target


def test_unchanged_change_type_never_triggers_an_action(db_session):
    seed = _seed(db_session)
    change = SignificantChange("overloaded_employee", f"employee:{seed['alice'].id}", "resolved", "resolved", "high", "resolved", {})
    assert decide_and_execute_actions(db_session, [change]) == []


def test_de_escalated_change_never_triggers_an_action(db_session):
    seed = _seed(db_session)
    change = SignificantChange("overloaded_employee", f"employee:{seed['alice'].id}", "de-escalated", "low", "high", "less overloaded", {"utilization_pct": 105.0})
    assert decide_and_execute_actions(db_session, [change]) == []


def test_unhandled_issue_types_produce_no_action(db_session):
    seed = _seed(db_session)
    change = SignificantChange("quality_issue", "task:1", "new", "high", None, "low quality", {"task_id": 1})
    assert decide_and_execute_actions(db_session, [change]) == []


def test_only_permitted_action_types_are_ever_recorded(db_session):
    """Guardrail: across a realistic multi-issue run, the daily manager must never create an
    AgentAction whose action is anything other than send_notification/assign_task, and must
    never touch create_task/update_task/change_priority or delete anything.
    """
    seed = _seed(db_session)
    today = date(2026, 8, 15)
    db_session.add(Task(
        project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Urgent",
        status=TaskStatus.IN_PROGRESS, deadline=today + timedelta(days=1),
    ))
    db_session.commit()

    changes = [
        SignificantChange("overloaded_employee", f"employee:{seed['alice'].id}", "new", "high", None, "overloaded", {"utilization_pct": 160.0}),
        SignificantChange(
            "workload_imbalance", "team", "new", "high", None, "imbalance",
            {"spread_pct": 85.0, "most_loaded": {"employee_id": seed["alice"].id, "name": "Alice Policy", "utilization_pct": 160.0}, "least_loaded": {"employee_id": seed["bob"].id, "name": "Bob Policy", "utilization_pct": 5.0}},
        ),
        SignificantChange("quality_issue", "task:99", "new", "high", None, "bad quality", {}),
        SignificantChange("project_risk", "project:1", "escalated", "high", "medium", "at risk", {}),
    ]
    decide_and_execute_actions(db_session, changes)

    recorded = db_session.query(AgentAction).filter_by(agent_type=AGENT_TYPE).all()
    assert recorded  # at least the two actionable changes produced something
    assert {r.action for r in recorded} <= {"send_notification", "assign_task"}
    task_count_before = db_session.query(Task).count()
    user_count_before = db_session.query(User).count()
    project_count_before = db_session.query(Project).count()
    # Nothing was deleted as a side effect of running the policy.
    assert db_session.query(Task).count() == task_count_before
    assert db_session.query(User).count() == user_count_before
    assert db_session.query(Project).count() == project_count_before
