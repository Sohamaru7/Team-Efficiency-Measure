"""API-level tests for /api/analytics/*, exercised through the FastAPI TestClient (`client`
fixture) against the same in-memory SQLite dataset used by the CRUD tests.
"""

from datetime import date

import pytest

from app.models.enums import ProjectStatus, TaskStatus
from app.models.project import Project
from app.models.task import Task
from app.models.user import User


def _seed(db_session):
    manager = User(name="Priya Shah", email="priya-api@example.com", department="Engineering")
    alice = User(name="Alice API", email="alice-api@example.com", department="Engineering")
    db_session.add_all([manager, alice])
    db_session.commit()

    project = Project(name="API Test Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()

    tasks = [
        Task(
            project_id=project.id, assigned_to=alice.id, title="Finished on time",
            status=TaskStatus.COMPLETED, estimated_hours=4, actual_hours=4, quality_score=95,
            deadline=date(2026, 8, 10), completed_date=date(2026, 8, 9),
        ),
        Task(
            project_id=project.id, assigned_to=alice.id, title="Overdue task",
            status=TaskStatus.NOT_STARTED, estimated_hours=3, deadline=date(2026, 8, 1),
        ),
        Task(
            project_id=project.id, assigned_to=alice.id, title="Blocked and close to deadline",
            status=TaskStatus.BLOCKED, estimated_hours=2, deadline=date(2026, 8, 16),
        ),
    ]
    db_session.add_all(tasks)
    db_session.commit()
    return {"manager": manager, "alice": alice, "project": project, "tasks": tasks}


def test_get_employee_score(client, db_session):
    seed = _seed(db_session)
    resp = client.get(f"/api/analytics/employees/{seed['alice'].id}/score", params={"as_of": "2026-08-14"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == seed["alice"].id
    assert body["overall_score"] is not None
    assert set(body["components"].keys()) == {
        "completion", "on_time", "quality", "time_efficiency",
        "deadline_adherence", "project_progress", "workload",
    }
    assert body["task_counts"]["total"] == 3


def test_get_employee_score_404_for_missing_user(client):
    resp = client.get("/api/analytics/employees/9999/score")
    assert resp.status_code == 404


def test_get_employee_workload(client, db_session):
    seed = _seed(db_session)
    resp = client.get(f"/api/analytics/employees/{seed['alice'].id}/workload", params={"capacity_hours": 10})
    assert resp.status_code == 200
    body = resp.json()
    # open tasks: overdue(3) + blocked(2) = 5 active hours; 5/10*100 = 50%
    assert body["active_hours"] == 5.0
    assert body["utilization_pct"] == 50.0
    assert body["score"] == 50.0
    assert body["active_task_count"] == 2


def test_get_employee_deadline_risk(client, db_session):
    seed = _seed(db_session)
    resp = client.get(f"/api/analytics/employees/{seed['alice'].id}/deadline-risk", params={"as_of": "2026-08-14"})
    assert resp.status_code == 200
    body = resp.json()
    risks_by_title = {r["title"]: r["risk"] for r in body}
    assert risks_by_title["Finished on time"] == "none"
    assert risks_by_title["Overdue task"] == "overdue"
    assert risks_by_title["Blocked and close to deadline"] == "high"
    # sorted most severe first
    assert [r["risk"] for r in body][0] == "overdue"


def test_get_employee_deadline_risk_min_risk_filter(client, db_session):
    seed = _seed(db_session)
    resp = client.get(
        f"/api/analytics/employees/{seed['alice'].id}/deadline-risk",
        params={"as_of": "2026-08-14", "min_risk": "high"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert all(r["risk"] in ("overdue", "high") for r in body)
    assert len(body) == 2  # overdue task + blocked task


def test_get_employee_delays(client, db_session):
    seed = _seed(db_session)
    resp = client.get(f"/api/analytics/employees/{seed['alice'].id}/delays", params={"as_of": "2026-08-14"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Overdue task"
    assert body[0]["is_delayed"] is True
    assert body[0]["delay_days"] == 13  # 2026-08-14 - 2026-08-01

    resp_all = client.get(
        f"/api/analytics/employees/{seed['alice'].id}/delays",
        params={"as_of": "2026-08-14", "only_delayed": False},
    )
    assert len(resp_all.json()) == 3


def test_get_project_progress(client, db_session):
    seed = _seed(db_session)
    resp = client.get(f"/api/analytics/projects/{seed['project'].id}/progress")
    assert resp.status_code == 200
    body = resp.json()
    # eligible weight = 4+3+2 = 9; completed weight = 4 -> 44.44%
    assert body["progress_pct"] == pytest.approx(400 / 9, rel=1e-6)
    assert body["total_tasks"] == 3
    assert body["completed_tasks"] == 1


def test_get_project_progress_404_for_missing_project(client):
    resp = client.get("/api/analytics/projects/9999/progress")
    assert resp.status_code == 404


def test_get_team_score(client, db_session):
    seed = _seed(db_session)
    resp = client.get(
        "/api/analytics/team/score",
        params={"user_ids": [seed["alice"].id, seed["manager"].id], "as_of": "2026-08-14"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["member_count"] == 2
    assert len(body["members"]) == 2


def test_get_team_score_by_department(client, db_session):
    _seed(db_session)
    resp = client.get("/api/analytics/team/score", params={"department": "Engineering"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["member_count"] == 2
