def _create_user(client, email):
    return client.post("/api/users", json={"name": "User", "email": email, "password": "correcthorse1"}).json()["id"]


def test_create_and_get_daily_update(client):
    user_id = _create_user(client, "du1@example.com")
    resp = client.post(
        "/api/daily-updates",
        json={"user_id": user_id, "date": "2026-08-14", "tasks_completed": 3, "tasks_pending": 2, "notes": "On track"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["tasks_completed"] == 3

    resp = client.get(f"/api/daily-updates/{body['id']}")
    assert resp.status_code == 200


def test_duplicate_daily_update_conflict(client):
    user_id = _create_user(client, "du2@example.com")
    payload = {"user_id": user_id, "date": "2026-08-14"}
    assert client.post("/api/daily-updates", json=payload).status_code == 201
    resp = client.post("/api/daily-updates", json=payload)
    assert resp.status_code == 409


def test_daily_update_negative_counts_rejected(client):
    user_id = _create_user(client, "du3@example.com")
    resp = client.post(
        "/api/daily-updates", json={"user_id": user_id, "date": "2026-08-14", "tasks_completed": -1}
    )
    assert resp.status_code == 422


def test_daily_update_crud_cycle(client):
    user_id = _create_user(client, "du4@example.com")
    obj_id = client.post("/api/daily-updates", json={"user_id": user_id, "date": "2026-08-13"}).json()["id"]

    resp = client.patch(f"/api/daily-updates/{obj_id}", json={"notes": "Updated"})
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Updated"

    assert client.delete(f"/api/daily-updates/{obj_id}").status_code == 204
    assert client.get(f"/api/daily-updates/{obj_id}").status_code == 404
