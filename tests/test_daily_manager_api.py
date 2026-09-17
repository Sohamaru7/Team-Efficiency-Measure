"""API-level tests for /api/daily-manager/* — the manual trigger and report history/detail
endpoints, exercised through the real FastAPI test client.
"""

from datetime import date

from app.models.enums import ProjectStatus, TaskPriority, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User


def _seed(db_session):
    manager = User(name="Manager API DM", email="mgr-api-dm@example.com", role=UserRole.MANAGER, department="Engineering")
    alice = User(name="Alice API DM", email="alice-api-dm@example.com", department="Engineering")
    db_session.add_all([manager, alice])
    db_session.commit()
    project = Project(name="API DM Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    return {"manager": manager, "alice": alice, "project": project}


def test_trigger_run_endpoint(client, db_session):
    _seed(db_session)
    resp = client.post("/api/daily-manager/run", params={"as_of": "2026-08-17"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ran"
    assert body["report"]["run_date"] == "2026-08-17"
    assert "team_efficiency" in body["report"]
    assert "recommended_actions" in body["report"]


def test_trigger_run_skips_weekend(client, db_session):
    _seed(db_session)
    resp = client.post("/api/daily-manager/run", params={"as_of": "2026-08-22"})  # Saturday
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "skipped_non_working_day"
    assert body["report"] is None


def test_trigger_run_twice_same_day_is_already_ran(client, db_session):
    _seed(db_session)
    first = client.post("/api/daily-manager/run", params={"as_of": "2026-08-17"})
    second = client.post("/api/daily-manager/run", params={"as_of": "2026-08-17"})
    assert first.json()["status"] == "ran"
    assert second.json()["status"] == "already_ran"
    assert second.json()["report"]["id"] == first.json()["report"]["id"]


def test_trigger_run_with_overload_produces_actions(client, db_session):
    seed = _seed(db_session)
    for i in range(5):
        db_session.add(Task(
            project_id=seed["project"].id, assigned_to=seed["alice"].id, title=f"Overload {i}",
            status=TaskStatus.IN_PROGRESS, priority=TaskPriority.HIGH, estimated_hours=20,
        ))
    db_session.commit()

    resp = client.post("/api/daily-manager/run", params={"as_of": "2026-08-17"})
    body = resp.json()
    assert body["report"]["action_required"] is True
    assert body["report"]["actions_taken_count"] >= 1
    assert any(a["action"] == "send_notification" for a in body["report"]["actions_taken"])


def test_list_reports(client, db_session):
    _seed(db_session)
    client.post("/api/daily-manager/run", params={"as_of": "2026-08-17"})
    client.post("/api/daily-manager/run", params={"as_of": "2026-08-18"})

    resp = client.get("/api/daily-manager/reports")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    # most recent first
    assert body[0]["run_date"] == "2026-08-18"
    assert "major_changes" not in body[0]  # summary schema is lighter than the detail schema


def test_get_latest_report(client, db_session):
    _seed(db_session)
    client.post("/api/daily-manager/run", params={"as_of": "2026-08-17"})
    client.post("/api/daily-manager/run", params={"as_of": "2026-08-18"})

    resp = client.get("/api/daily-manager/reports/latest")
    assert resp.status_code == 200
    assert resp.json()["run_date"] == "2026-08-18"


def test_get_latest_report_404_when_none_exist(client):
    resp = client.get("/api/daily-manager/reports/latest")
    assert resp.status_code == 404


def test_get_report_by_id(client, db_session):
    _seed(db_session)
    run_resp = client.post("/api/daily-manager/run", params={"as_of": "2026-08-17"})
    report_id = run_resp.json()["report"]["id"]

    resp = client.get(f"/api/daily-manager/reports/{report_id}")
    assert resp.status_code == 200
    assert resp.json()["run_date"] == "2026-08-17"


def test_get_report_404_for_missing_id(client):
    resp = client.get("/api/daily-manager/reports/999999")
    assert resp.status_code == 404


def test_force_rerun_replaces_report(client, db_session):
    from app.models.daily_manager import DailyManagerReport

    seed = _seed(db_session)
    first = client.post("/api/daily-manager/run", params={"as_of": "2026-08-17"})
    assert len(first.json()["report"]["completed_work"]) == 0

    db_session.add(Task(project_id=seed["project"].id, assigned_to=seed["alice"].id, title="New", status=TaskStatus.COMPLETED, completed_date=date(2026, 8, 17)))
    db_session.commit()

    forced = client.post("/api/daily-manager/run", params={"as_of": "2026-08-17", "force": "true"})
    assert forced.json()["status"] == "ran"
    assert len(forced.json()["report"]["completed_work"]) == 1

    # run_date stays unique -- the old report row was replaced, not accumulated alongside a new one.
    assert db_session.query(DailyManagerReport).filter_by(run_date=date(2026, 8, 17)).count() == 1
