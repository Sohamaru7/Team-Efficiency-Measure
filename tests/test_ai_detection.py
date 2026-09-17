"""Unit tests for app.services.ai.detection — the deterministic detectors behind the agent's
Observe/Analyze/Identify-problem steps. Every threshold crossed here is checked against a
hand-picked dataset so the pass/fail boundary of each detector is verified precisely, not just
"it ran without crashing."
"""

from datetime import date, timedelta

import pytest

from app.models.daily_update import DailyUpdate
from app.models.enums import ProjectStatus, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.ai import detection

AS_OF = date(2026, 8, 14)


def _seed_workload_scenario(db_session):
    manager = User(name="Manager", email="mgr-detect@example.com", role=UserRole.MANAGER, department="Management")
    overloaded = User(name="Overloaded Owen", email="owen-detect@example.com", department="Engineering")
    idle = User(name="Idle Ivy", email="ivy-detect@example.com", department="Engineering")
    db_session.add_all([manager, overloaded, idle])
    db_session.commit()

    project = Project(name="Detect Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()

    # Owen: 50 active hours against a 40-hour default capacity -> 125% -> overloaded.
    # Ivy: 2 active hours -> 5% -> underutilized.
    db_session.add_all(
        [
            Task(project_id=project.id, assigned_to=overloaded.id, title="Big task", status=TaskStatus.IN_PROGRESS, estimated_hours=50),
            Task(project_id=project.id, assigned_to=idle.id, title="Small task", status=TaskStatus.NOT_STARTED, estimated_hours=2),
        ]
    )
    db_session.commit()
    return {"manager": manager, "overloaded": overloaded, "idle": idle, "project": project}


def test_detect_issues_flags_overloaded_and_underutilized(db_session):
    seed = _seed_workload_scenario(db_session)
    result = detection.detect_issues(db_session, department="Engineering", as_of=str(AS_OF))

    overloaded_ids = {e["employee_id"] for e in result["overloaded_employees"]}
    underutilized_ids = {e["employee_id"] for e in result["underutilized_employees"]}
    assert seed["overloaded"].id in overloaded_ids
    assert seed["idle"].id in underutilized_ids
    assert seed["overloaded"].id not in underutilized_ids
    assert seed["idle"].id not in overloaded_ids


def test_detect_issues_flags_workload_imbalance(db_session):
    _seed_workload_scenario(db_session)
    result = detection.detect_issues(db_session, department="Engineering", as_of=str(AS_OF))
    imbalance = result["workload_imbalance"]
    assert imbalance is not None
    assert imbalance["spread_pct"] > detection.WORKLOAD_IMBALANCE_SPREAD_PCT
    assert imbalance["most_loaded"]["name"] == "Overloaded Owen"
    assert imbalance["least_loaded"]["name"] == "Idle Ivy"


def test_detect_issues_no_imbalance_when_balanced(db_session):
    manager = User(name="Manager2", email="mgr2-detect@example.com", department="Management")
    a = User(name="A", email="a-detect@example.com", department="Balanced")
    b = User(name="B", email="b-detect@example.com", department="Balanced")
    db_session.add_all([manager, a, b])
    db_session.commit()
    project = Project(name="Balanced Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    db_session.add_all(
        [
            Task(project_id=project.id, assigned_to=a.id, title="T1", status=TaskStatus.IN_PROGRESS, estimated_hours=20),
            Task(project_id=project.id, assigned_to=b.id, title="T2", status=TaskStatus.IN_PROGRESS, estimated_hours=22),
        ]
    )
    db_session.commit()

    result = detection.detect_issues(db_session, department="Balanced", as_of=str(AS_OF))
    assert result["workload_imbalance"] is None
    assert result["overloaded_employees"] == []
    assert result["underutilized_employees"] == []


def test_detect_issues_approaching_deadlines_and_delayed_tasks(db_session):
    manager = User(name="Manager3", email="mgr3-detect@example.com", department="Management")
    carol = User(name="Carol", email="carol-detect@example.com", department="Ops")
    db_session.add_all([manager, carol])
    db_session.commit()
    project = Project(name="Deadline Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    db_session.add_all(
        [
            Task(project_id=project.id, assigned_to=carol.id, title="Due soon", status=TaskStatus.IN_PROGRESS,
                 estimated_hours=3, deadline=AS_OF + timedelta(days=1)),
            Task(project_id=project.id, assigned_to=carol.id, title="Overdue task", status=TaskStatus.NOT_STARTED,
                 estimated_hours=2, deadline=AS_OF - timedelta(days=5), delay_reason="waiting on vendor"),
        ]
    )
    db_session.commit()

    result = detection.detect_issues(db_session, department="Ops", as_of=str(AS_OF))
    approaching_titles = {t["title"] for t in result["approaching_deadlines"]}
    delayed_titles = {t["title"] for t in result["delayed_tasks"]}
    assert "Due soon" in approaching_titles
    assert "Overdue task" in delayed_titles


def test_detect_recurring_delay_causes(db_session):
    manager = User(name="Manager4", email="mgr4-detect@example.com", department="Management")
    dave = User(name="Dave", email="dave-detect@example.com", department="Ops2")
    db_session.add_all([manager, dave])
    db_session.commit()
    project = Project(name="Recurring Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    db_session.add_all(
        [
            Task(project_id=project.id, assigned_to=dave.id, title="T1", status=TaskStatus.NOT_STARTED,
                 estimated_hours=1, deadline=AS_OF - timedelta(days=2), delay_reason="Waiting on vendor"),
            Task(project_id=project.id, assigned_to=dave.id, title="T2", status=TaskStatus.NOT_STARTED,
                 estimated_hours=1, deadline=AS_OF - timedelta(days=3), delay_reason="waiting on VENDOR"),
            Task(project_id=project.id, assigned_to=dave.id, title="T3", status=TaskStatus.NOT_STARTED,
                 estimated_hours=1, deadline=AS_OF - timedelta(days=1), delay_reason="Scope changed"),
        ]
    )
    db_session.commit()

    result = detection.detect_issues(db_session, department="Ops2", as_of=str(AS_OF))
    recurring = result["recurring_delay_causes"]
    assert len(recurring) == 1
    assert recurring[0]["reason"] == "waiting on vendor"
    assert recurring[0]["occurrences"] == 2


def test_detect_performance_drops_needs_enough_data(db_session):
    manager = User(name="Manager5", email="mgr5-detect@example.com", department="Management")
    erin = User(name="Erin", email="erin-detect@example.com", department="Data")
    db_session.add_all([manager, erin])
    db_session.commit()

    # Only 1 daily update -> not enough points to judge a drop either way.
    db_session.add(DailyUpdate(user_id=erin.id, date=AS_OF, tasks_completed=1, tasks_pending=1))
    db_session.commit()

    result = detection.detect_issues(db_session, department="Data", as_of=str(AS_OF))
    assert result["performance_drops"] == []


def test_detect_performance_drops_flags_real_drop(db_session):
    manager = User(name="Manager6", email="mgr6-detect@example.com", department="Management")
    frank = User(name="Frank", email="frank-detect@example.com", department="Support")
    db_session.add_all([manager, frank])
    db_session.commit()

    # Earlier half: high completion ratio. Later half: much lower. 6 points total (>=4 minimum).
    updates = [
        DailyUpdate(user_id=frank.id, date=AS_OF - timedelta(days=5), tasks_completed=9, tasks_pending=1),
        DailyUpdate(user_id=frank.id, date=AS_OF - timedelta(days=4), tasks_completed=9, tasks_pending=1),
        DailyUpdate(user_id=frank.id, date=AS_OF - timedelta(days=3), tasks_completed=9, tasks_pending=1),
        DailyUpdate(user_id=frank.id, date=AS_OF - timedelta(days=2), tasks_completed=1, tasks_pending=9),
        DailyUpdate(user_id=frank.id, date=AS_OF - timedelta(days=1), tasks_completed=1, tasks_pending=9),
        DailyUpdate(user_id=frank.id, date=AS_OF, tasks_completed=1, tasks_pending=9),
    ]
    db_session.add_all(updates)
    db_session.commit()

    result = detection.detect_issues(db_session, department="Support", as_of=str(AS_OF))
    drops = result["performance_drops"]
    assert len(drops) == 1
    assert drops[0]["employee_id"] == frank.id
    assert drops[0]["drop_pct"] > detection.PERFORMANCE_DROP_THRESHOLD_PCT


def test_detect_issues_empty_department_returns_all_empty(db_session):
    result = detection.detect_issues(db_session, department="NoSuchDepartment", as_of=str(AS_OF))
    assert result["overloaded_employees"] == []
    assert result["underutilized_employees"] == []
    assert result["approaching_deadlines"] == []
    assert result["delayed_tasks"] == []
    assert result["performance_drops"] == []
    assert result["workload_imbalance"] is None
    assert result["recurring_delay_causes"] == []
