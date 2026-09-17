"""API-level tests for GET /api/dashboard, through the FastAPI TestClient."""

from datetime import date

from app.models.enums import ProjectStatus, TaskStatus
from app.models.project import Project
from app.models.task import Task
from app.models.user import User


def _seed(db_session):
    manager = User(name="Dana Manager", email="dana-api@example.com", department="Management")
    alice = User(name="Alice API2", email="alice-api2@example.com", department="Engineering")
    db_session.add_all([manager, alice])
    db_session.commit()

    project = Project(name="Dashboard API Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()

    tasks = [
        Task(
            project_id=project.id, assigned_to=alice.id, title="Completed on time",
            status=TaskStatus.COMPLETED, estimated_hours=4,
            start_date=date(2026, 8, 1), completed_date=date(2026, 8, 5), deadline=date(2026, 8, 10),
        ),
        Task(
            project_id=project.id, assigned_to=alice.id, title="Overdue",
            status=TaskStatus.NOT_STARTED, estimated_hours=3, deadline=date(2026, 8, 1),
        ),
    ]
    db_session.add_all(tasks)
    db_session.commit()
    return {"manager": manager, "alice": alice, "project": project}


def test_get_dashboard_default_scope(client, db_session):
    _seed(db_session)
    resp = client.get("/api/dashboard", params={"as_of": "2026-08-14"})
    assert resp.status_code == 200
    body = resp.json()
    assert "summary" in body
    assert body["summary"]["tasks_completed"] == 1
    assert body["summary"]["tasks_overdue"] == 1
    assert set(body.keys()) >= {
        "summary", "employee_performance", "workload_distribution",
        "project_progress", "delayed_tasks", "upcoming_deadlines", "efficiency_trend",
    }


def test_get_dashboard_filters_by_employee(client, db_session):
    seed = _seed(db_session)
    resp = client.get("/api/dashboard", params={"employee_id": seed["alice"].id, "as_of": "2026-08-14"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["team_size"] == 1
    assert len(body["employee_performance"]) == 1
    assert body["employee_performance"][0]["user_id"] == seed["alice"].id


def test_get_dashboard_filters_by_project(client, db_session):
    seed = _seed(db_session)
    resp = client.get("/api/dashboard", params={"project_id": seed["project"].id, "as_of": "2026-08-14"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["project_progress"]) == 1
    assert body["project_progress"][0]["project_id"] == seed["project"].id


def test_get_dashboard_404_for_missing_employee(client):
    resp = client.get("/api/dashboard", params={"employee_id": 9999})
    assert resp.status_code == 404


def test_get_dashboard_404_for_missing_project(client):
    resp = client.get("/api/dashboard", params={"project_id": 9999})
    assert resp.status_code == 404


def test_get_dashboard_rejects_inverted_date_range(client):
    resp = client.get("/api/dashboard", params={"date_from": "2026-08-14", "date_to": "2026-08-01"})
    assert resp.status_code == 422


def test_get_dashboard_status_filter(client, db_session):
    _seed(db_session)
    resp = client.get("/api/dashboard", params={"status": "not_started", "as_of": "2026-08-14"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["tasks_completed"] == 0
    assert body["summary"]["tasks_overdue"] == 1
