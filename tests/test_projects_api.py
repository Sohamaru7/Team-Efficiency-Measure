def _create_user(client, email):
    return client.post(
        "/api/users", json={"name": "Manager", "email": email, "role": "manager", "password": "correcthorse1"}
    ).json()["id"]


def test_create_project(client):
    manager_id = _create_user(client, "mgr@example.com")
    resp = client.post(
        "/api/projects",
        json={
            "name": "Website Revamp",
            "description": "Redesign marketing site",
            "manager_id": manager_id,
            "start_date": "2026-01-01",
            "deadline": "2026-03-01",
            "status": "planning",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Website Revamp"
    assert body["manager_id"] == manager_id


def test_project_invalid_date_range_rejected(client):
    manager_id = _create_user(client, "mgr2@example.com")
    resp = client.post(
        "/api/projects",
        json={"name": "Bad Dates", "manager_id": manager_id, "start_date": "2026-03-01", "deadline": "2026-01-01"},
    )
    assert resp.status_code == 422


def test_project_crud_cycle(client):
    manager_id = _create_user(client, "mgr3@example.com")
    resp = client.post("/api/projects", json={"name": "Temp Project", "manager_id": manager_id})
    project_id = resp.json()["id"]

    resp = client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200

    resp = client.patch(f"/api/projects/{project_id}", json={"status": "active"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"

    resp = client.delete(f"/api/projects/{project_id}")
    assert resp.status_code == 204
    assert client.get(f"/api/projects/{project_id}").status_code == 404


def test_project_invalid_manager_rejected(client):
    resp = client.post("/api/projects", json={"name": "Ghost Manager", "manager_id": 9999})
    assert resp.status_code == 400


def test_list_projects_filter_by_status(client):
    manager_id = _create_user(client, "mgr4@example.com")
    client.post("/api/projects", json={"name": "P1", "manager_id": manager_id, "status": "active"})
    client.post("/api/projects", json={"name": "P2", "manager_id": manager_id, "status": "planning"})

    resp = client.get("/api/projects", params={"status": "active"})
    assert resp.status_code == 200
    assert all(p["status"] == "active" for p in resp.json())
