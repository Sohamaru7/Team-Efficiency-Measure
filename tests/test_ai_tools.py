"""Unit tests for app.services.ai.tools — the controlled, read-only functions exposed to the
Manager AI Assistant. These are plain Python function tests (no LLM, no network): each test
seeds a small realistic dataset into SQLite and asserts the tool's JSON-shaped output, since
every tool is just a thin wrapper around the already-tested Phase 4/5 analytics engine.
"""

from datetime import date

import pytest

from app.models.enums import ProjectStatus, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.ai import tools

AS_OF = "2026-08-14"


def _seed(db_session):
    manager = User(name="Priya Shah", email="priya-ai@example.com", role=UserRole.MANAGER, department="Management")
    alice = User(name="Alice AI", email="alice-ai@example.com", department="Engineering")
    bob = User(name="Bob AI", email="bob-ai@example.com", department="Engineering")
    db_session.add_all([manager, alice, bob])
    db_session.commit()

    project = Project(name="AI Test Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()

    tasks_list = [
        Task(
            project_id=project.id, assigned_to=alice.id, title="Completed on time",
            status=TaskStatus.COMPLETED, estimated_hours=4, actual_hours=4, quality_score=90,
            start_date=date(2026, 8, 1), completed_date=date(2026, 8, 5), deadline=date(2026, 8, 10),
        ),
        Task(
            project_id=project.id, assigned_to=alice.id, title="Overdue task",
            status=TaskStatus.NOT_STARTED, estimated_hours=3, deadline=date(2026, 8, 1),
            delay_reason="waiting on design sign-off",
        ),
        Task(
            project_id=project.id, assigned_to=bob.id, title="At risk task",
            status=TaskStatus.IN_PROGRESS, estimated_hours=5, deadline=date(2026, 8, 16),
        ),
        Task(
            project_id=project.id, assigned_to=bob.id, title="Comfortable task",
            status=TaskStatus.IN_PROGRESS, estimated_hours=8, deadline=date(2026, 9, 1),
        ),
    ]
    db_session.add_all(tasks_list)
    db_session.commit()

    return {"manager": manager, "alice": alice, "bob": bob, "project": project}


def test_get_team_metrics(db_session):
    seed = _seed(db_session)
    result = tools.get_team_metrics(db_session, department="Engineering", as_of=AS_OF)
    assert result["department"] == "Engineering"
    assert result["team_size"] == 2
    assert result["overall_efficiency_score"] is not None
    assert set(result["component_averages"]) == {
        "completion", "on_time", "quality", "time_efficiency", "deadline_adherence", "project_progress", "workload",
    }


def test_get_employee_metrics(db_session):
    seed = _seed(db_session)
    result = tools.get_employee_metrics(db_session, seed["alice"].id)
    assert result["name"] == "Alice AI"
    assert result["overall_efficiency_score"] is not None
    assert result["task_counts"]["total"] == 2


def test_get_employee_metrics_missing_employee(db_session):
    result = tools.get_employee_metrics(db_session, 999999)
    assert "error" in result


def test_get_project_metrics(db_session):
    seed = _seed(db_session)
    result = tools.get_project_metrics(db_session, seed["project"].id)
    assert result["name"] == "AI Test Project"
    assert result["total_tasks"] == 4
    assert result["completed_tasks"] == 1


def test_get_project_metrics_missing_project(db_session):
    result = tools.get_project_metrics(db_session, 999999)
    assert "error" in result


def test_get_overdue_tasks(db_session):
    seed = _seed(db_session)
    result = tools.get_overdue_tasks(db_session, department="Engineering", as_of=AS_OF)
    assert len(result) == 1
    assert result[0]["title"] == "Overdue task"
    assert result[0]["days_overdue"] == 13
    assert result[0]["assignee"] == "Alice AI"


def test_get_at_risk_tasks(db_session):
    seed = _seed(db_session)
    result = tools.get_at_risk_tasks(db_session, department="Engineering", as_of=AS_OF)
    titles = {r["title"] for r in result}
    assert "At risk task" in titles
    assert "Comfortable task" not in titles


def test_get_workload_single_employee(db_session):
    seed = _seed(db_session)
    result = tools.get_workload(db_session, employee_id=seed["bob"].id, capacity_hours=40)
    assert result["name"] == "Bob AI"
    assert result["active_hours"] == 13.0  # 5 + 8


def test_get_workload_missing_employee(db_session):
    result = tools.get_workload(db_session, employee_id=999999)
    assert "error" in result


def test_get_workload_department_list_sorted_desc(db_session):
    seed = _seed(db_session)
    result = tools.get_workload(db_session, department="Engineering", capacity_hours=40)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["utilization_pct"] >= result[1]["utilization_pct"]


def test_get_recent_delays(db_session):
    seed = _seed(db_session)
    result = tools.get_recent_delays(db_session, days=30, department="Engineering", as_of=AS_OF)
    assert len(result) == 1
    assert result[0]["title"] == "Overdue task"
    assert result[0]["delay_reason"] == "waiting on design sign-off"


def test_get_recent_delays_narrow_window_excludes(db_session):
    seed = _seed(db_session)
    # deadline 2026-08-01 falls outside a window that only covers the last 3 days
    result = tools.get_recent_delays(db_session, days=3, department="Engineering", as_of=AS_OF)
    assert result == []


def test_get_quality_metrics_single_employee(db_session):
    seed = _seed(db_session)
    result = tools.get_quality_metrics(db_session, employee_id=seed["alice"].id)
    assert result["quality_score"] == 90.0


def test_get_quality_metrics_department(db_session):
    seed = _seed(db_session)
    result = tools.get_quality_metrics(db_session, department="Engineering")
    # only alice has a completed task with a quality_score
    assert result["team_average_quality_score"] == 90.0
    assert len(result["employees"]) == 1
    assert result["employees"][0]["name"] == "Alice AI"


def test_all_tool_functions_are_json_serializable(db_session):
    import json

    seed = _seed(db_session)
    for name, func in tools.TOOL_FUNCTIONS.items():
        if name in ("get_employee_metrics",):
            result = func(db_session, seed["alice"].id)
        elif name == "get_project_metrics":
            result = func(db_session, seed["project"].id)
        else:
            result = func(db_session)
        json.dumps(result, default=str)  # must not raise
