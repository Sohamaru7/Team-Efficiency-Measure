"""API-level tests for /api/emails/* — ingestion (JSON + .eml upload), listing (redacted),
detail (permission-gated), signals, and delay-classification, exercised through the real
FastAPI test client.
"""

from datetime import date, datetime

from app.models.email import Email
from app.models.enums import EmailDirection, ProjectStatus, TaskPriority, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User


def _seed(db_session):
    manager = User(name="Manager EmailAPI", email="mgr-emailapi@ourcompany.com", role=UserRole.MANAGER, department="Engineering")
    alice = User(name="Alice EmailAPI", email="alice-emailapi@ourcompany.com", role=UserRole.EMPLOYEE, department="Engineering")
    bob = User(name="Bob EmailAPI", email="bob-emailapi@ourcompany.com", role=UserRole.EMPLOYEE, department="Engineering")
    db_session.add_all([manager, alice, bob])
    db_session.commit()
    project = Project(name="EmailAPI Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    task = Task(project_id=project.id, assigned_to=alice.id, title="Ship it", status=TaskStatus.IN_PROGRESS)
    db_session.add(task)
    db_session.commit()
    return {"manager": manager, "alice": alice, "bob": bob, "project": project, "task": task}


def test_ingest_email_json(client, db_session):
    seed = _seed(db_session)
    resp = client.post(
        "/api/emails",
        json={
            "task_id": seed["task"].id, "from_address": "alice-emailapi@ourcompany.com",
            "to_addresses": ["client@clientco.com"], "subject": "Kickoff", "sent_at": "2026-08-01T09:00:00",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["direction"] == "outbound"
    assert body["is_external"] is True
    assert body["project_id"] == seed["project"].id  # derived from the task


def test_ingest_email_requires_task_or_project(client):
    resp = client.post(
        "/api/emails",
        json={"from_address": "a@b.com", "to_addresses": ["c@d.com"], "sent_at": "2026-08-01T09:00:00"},
    )
    assert resp.status_code == 422


def test_ingest_email_unknown_task_404(client):
    resp = client.post(
        "/api/emails",
        json={"task_id": 999999, "from_address": "a@b.com", "to_addresses": ["c@d.com"], "sent_at": "2026-08-01T09:00:00"},
    )
    assert resp.status_code == 404


def test_ingest_email_duplicate_message_id_409(client, db_session):
    seed = _seed(db_session)
    payload = {
        "task_id": seed["task"].id, "from_address": "alice-emailapi@ourcompany.com",
        "to_addresses": ["client@clientco.com"], "sent_at": "2026-08-01T09:00:00", "message_id": "<dup@x.com>",
    }
    first = client.post("/api/emails", json=payload)
    assert first.status_code == 201
    second = client.post("/api/emails", json=payload)
    assert second.status_code == 409


def test_ingest_eml_file(client, db_session):
    seed = _seed(db_session)
    raw = (
        b"From: Client <client@clientco.com>\r\n"
        b"To: Alice <alice-emailapi@ourcompany.com>\r\n"
        b"Subject: Project update\r\n"
        b"Date: Mon, 10 Aug 2026 09:30:00 +0000\r\n\r\n"
        b"Here is the update.\r\n"
    )
    resp = client.post(
        "/api/emails/ingest-eml",
        files={"file": ("email.eml", raw, "message/rfc822")},
        data={"task_id": str(seed["task"].id)},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["direction"] == "inbound"
    assert body["subject"] == "Project update"


def test_ingest_eml_missing_date_returns_422(client, db_session):
    seed = _seed(db_session)
    raw = b"From: client@clientco.com\r\nSubject: no date\r\n\r\nBody\r\n"
    resp = client.post(
        "/api/emails/ingest-eml", files={"file": ("bad.eml", raw, "message/rfc822")}, data={"task_id": str(seed["task"].id)}
    )
    assert resp.status_code == 422


def test_list_emails_is_redacted(client, db_session):
    seed = _seed(db_session)
    db_session.add(Email(
        task_id=seed["task"].id, subject="Secret subject", from_address="alice-emailapi@ourcompany.com",
        to_addresses="client@clientco.com", direction=EmailDirection.OUTBOUND, is_external=True,
        sent_at=datetime(2026, 8, 1, 9, 0), body_text="secret body",
    ))
    db_session.commit()

    resp = client.get("/api/emails", params={"task_id": seed["task"].id})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert "subject" not in body[0]
    assert "body_text" not in body[0]
    assert "from_address" not in body[0]
    assert body[0]["has_body"] is True


def test_get_email_detail_requires_permission(client, client_as, db_session):
    from app.api.deps import get_current_user
    from app.main import app

    seed = _seed(db_session)
    email_row = Email(
        task_id=seed["task"].id, subject="Secret subject", from_address="alice-emailapi@ourcompany.com",
        to_addresses="client@clientco.com", direction=EmailDirection.OUTBOUND, is_external=True,
        sent_at=datetime(2026, 8, 1, 9, 0),
    )
    db_session.add(email_row)
    db_session.commit()

    denied = client_as(seed["bob"]).get(f"/api/emails/{email_row.id}")
    assert denied.status_code == 403

    allowed = client_as(seed["alice"]).get(f"/api/emails/{email_row.id}")
    assert allowed.status_code == 200
    assert allowed.json()["subject"] == "Secret subject"

    # No Authorization header at all -- clear the test-only auth override so this request goes
    # through real bearer-token verification (see conftest.unauthenticated_client for the same
    # pattern as its own fixture; done inline here since this test needs both real-role checks
    # *and* the no-token case within one flow).
    app.dependency_overrides.pop(get_current_user, None)
    no_token = client.get(f"/api/emails/{email_row.id}")
    assert no_token.status_code == 401


def test_get_email_detail_404(client):
    resp = client.get("/api/emails/999999")
    assert resp.status_code == 404


def test_task_signals_endpoint_permission_and_content(client, client_as, db_session):
    seed = _seed(db_session)
    db_session.add_all([
        Email(
            task_id=seed["task"].id, from_address="alice-emailapi@ourcompany.com", to_addresses="client@clientco.com",
            direction=EmailDirection.OUTBOUND, is_external=True, sent_at=datetime(2026, 8, 1, 9, 0),
        ),
        Email(
            task_id=seed["task"].id, from_address="client@clientco.com", to_addresses="alice-emailapi@ourcompany.com",
            direction=EmailDirection.INBOUND, is_external=True, sent_at=datetime(2026, 8, 3, 9, 0),
        ),
    ])
    db_session.commit()

    denied = client_as(seed["bob"]).get(f"/api/emails/tasks/{seed['task'].id}/signals")
    assert denied.status_code == 403

    resp = client_as(seed["alice"]).get(f"/api/emails/tasks/{seed['task'].id}/signals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["communication"]["email_count"] == 2
    assert body["client_response_delay"]["gap_days"] == 2


def test_task_signals_404_for_missing_task(client):
    resp = client.get("/api/emails/tasks/999999/signals")
    assert resp.status_code == 404


def test_delay_classification_endpoint_matches_brief_example(client, client_as, db_session):
    seed = _seed(db_session)
    task = Task(
        project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Delayed task",
        status=TaskStatus.IN_PROGRESS, priority=TaskPriority.HIGH,
        deadline=date(2026, 8, 10), delay_reason="waiting for client",
    )
    db_session.add(task)
    db_session.commit()
    db_session.add_all([
        Email(
            task_id=task.id, from_address="alice-emailapi@ourcompany.com", to_addresses="client@clientco.com",
            direction=EmailDirection.OUTBOUND, is_external=True, sent_at=datetime(2026, 8, 10, 9, 0),
        ),
        Email(
            task_id=task.id, from_address="client@clientco.com", to_addresses="alice-emailapi@ourcompany.com",
            direction=EmailDirection.INBOUND, is_external=True, sent_at=datetime(2026, 8, 12, 9, 0),
        ),
    ])
    db_session.commit()

    resp = client_as(seed["alice"]).get(
        f"/api/emails/tasks/{task.id}/delay-classification", params={"as_of": "2026-08-20"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["delay_type"] == "external"
    assert body["cause"] == "Client response delay"
    assert body["duration_days"] == 2


def test_delay_classification_403_without_permission(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["bob"]).get(f"/api/emails/tasks/{seed['task'].id}/delay-classification")
    assert resp.status_code == 403
