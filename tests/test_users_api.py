def test_create_and_get_user(client):
    resp = client.post(
        "/api/users",
        json={
            "name": "Alice", "email": "alice@example.com", "role": "manager",
            "department": "Engineering", "password": "correcthorse1",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert body["role"] == "manager"
    assert "password" not in body
    assert "hashed_password" not in body
    user_id = body["id"]

    resp = client.get(f"/api/users/{user_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Alice"


def test_duplicate_email_conflict(client):
    payload = {"name": "Bob", "email": "bob@example.com", "password": "correcthorse1"}
    assert client.post("/api/users", json=payload).status_code == 201
    resp = client.post("/api/users", json=payload)
    assert resp.status_code == 409


def test_list_update_and_delete_user(client):
    resp = client.post("/api/users", json={"name": "Carol", "email": "carol@example.com", "password": "correcthorse1"})
    user_id = resp.json()["id"]

    resp = client.get("/api/users")
    assert resp.status_code == 200
    assert any(u["id"] == user_id for u in resp.json())

    resp = client.patch(f"/api/users/{user_id}", json={"active": False})
    assert resp.status_code == 200
    assert resp.json()["active"] is False

    resp = client.delete(f"/api/users/{user_id}")
    assert resp.status_code == 204
    assert client.get(f"/api/users/{user_id}").status_code == 404


def test_get_missing_user_404(client):
    assert client.get("/api/users/9999").status_code == 404


def test_invalid_email_rejected(client):
    resp = client.post("/api/users", json={"name": "Dave", "email": "not-an-email", "password": "correcthorse1"})
    assert resp.status_code == 422


def test_missing_password_rejected(client):
    resp = client.post("/api/users", json={"name": "Eve", "email": "eve@example.com"})
    assert resp.status_code == 422


def test_weak_password_rejected(client):
    resp = client.post("/api/users", json={"name": "Frank", "email": "frank@example.com", "password": "short"})
    assert resp.status_code == 422
