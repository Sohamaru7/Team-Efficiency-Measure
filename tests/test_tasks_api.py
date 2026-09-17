from app.models.task_history import TaskHistory
from app.models.user import User
from tests.conftest import TEST_ADMIN_EMAIL


def _create_user(client, email):
    return client.post("/api/users", json={"name": "User", "email": email, "password": "correcthorse1"}).json()["id"]


def _create_project(client, manager_id):
    return client.post("/api/projects", json={"name": "Project X", "manager_id": manager_id}).json()["id"]


def test_create_task_logs_initial_history(client, db_session):
    manager_id = _create_user(client, "pm@example.com")
    project_id = _create_project(client, manager_id)
    assignee_id = _create_user(client, "dev@example.com")

    resp = client.post(
        "/api/tasks",
        json={
            "project_id": project_id,
            "assigned_to": assignee_id,
            "title": "Implement login",
            "priority": "high",
            "estimated_hours": "8.00",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    task_id = body["id"]
    assert body["status"] == "not_started"

    history = db_session.query(TaskHistory).filter_by(task_id=task_id).all()
    assert len(history) == 1
    assert history[0].old_status is None
    assert history[0].new_status.value == "not_started"


def test_update_task_status_logs_history(client, db_session):
    manager_id = _create_user(client, "pm2@example.com")
    project_id = _create_project(client, manager_id)

    task_id = client.post("/api/tasks", json={"project_id": project_id, "title": "Task A"}).json()["id"]

    # changed_by is deliberately NOT taken from the request body (a client-supplied id is never
    # trusted for attribution — see app.api.routes.tasks.update_task) — it's always the real
    # authenticated caller, the default test-admin for the `client` fixture.
    resp = client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress", "changed_by": manager_id})
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"

    admin_id = db_session.query(User).filter_by(email=TEST_ADMIN_EMAIL).one().id

    history = db_session.query(TaskHistory).filter_by(task_id=task_id).order_by(TaskHistory.id).all()
    assert len(history) == 2
    assert history[1].old_status.value == "not_started"
    assert history[1].new_status.value == "in_progress"
    assert history[1].changed_by == admin_id
    assert history[1].changed_by != manager_id


def test_task_quality_score_out_of_range_rejected(client):
    manager_id = _create_user(client, "pm3@example.com")
    project_id = _create_project(client, manager_id)
    resp = client.post(
        "/api/tasks", json={"project_id": project_id, "title": "Bad score", "quality_score": 150}
    )
    assert resp.status_code == 422


def test_task_negative_hours_rejected(client):
    manager_id = _create_user(client, "pm5@example.com")
    project_id = _create_project(client, manager_id)
    resp = client.post(
        "/api/tasks", json={"project_id": project_id, "title": "Bad hours", "estimated_hours": -1}
    )
    assert resp.status_code == 422


def test_task_invalid_project_rejected(client):
    resp = client.post("/api/tasks", json={"project_id": 9999, "title": "Orphan task"})
    assert resp.status_code == 400


def test_task_crud_cycle(client):
    manager_id = _create_user(client, "pm4@example.com")
    project_id = _create_project(client, manager_id)
    task_id = client.post("/api/tasks", json={"project_id": project_id, "title": "Temp"}).json()["id"]

    assert client.get(f"/api/tasks/{task_id}").status_code == 200
    assert client.delete(f"/api/tasks/{task_id}").status_code == 204
    assert client.get(f"/api/tasks/{task_id}").status_code == 404
