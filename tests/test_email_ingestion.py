"""DB-integration tests for app.services.emailing.ingestion — .eml parsing, direction/
is_external computation from real User domains, and the ingest_email insertion path.
"""

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.enums import ProjectStatus, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.emailing.ingestion import (
    EmailIngestData,
    InvalidEmailError,
    compute_direction_and_external,
    ingest_email,
    parse_eml,
)


def _seed(db_session):
    manager = User(name="Manager Email", email="mgr@ourcompany.com", role=UserRole.MANAGER, department="Engineering")
    alice = User(name="Alice Email", email="alice@ourcompany.com", role=UserRole.EMPLOYEE, department="Engineering")
    db_session.add_all([manager, alice])
    db_session.commit()
    project = Project(name="Client Portal", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    task = Task(project_id=project.id, assigned_to=alice.id, title="Build login flow", status=TaskStatus.IN_PROGRESS)
    db_session.add(task)
    db_session.commit()
    return {"manager": manager, "alice": alice, "project": project, "task": task}


# --------------------------------------------------------------------------------- parse_eml ----


def test_parse_eml_basic():
    raw = (
        b"From: Client <client@clientco.com>\r\n"
        b"To: Alice <alice@ourcompany.com>\r\n"
        b"Subject: Project update\r\n"
        b"Date: Mon, 10 Aug 2026 09:30:00 +0000\r\n"
        b"Message-Id: <abc@clientco.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Here is the update.\r\n"
    )
    parsed = parse_eml(raw)
    assert parsed.from_address == "client@clientco.com"
    assert parsed.to_addresses == ["alice@ourcompany.com"]
    assert parsed.subject == "Project update"
    assert parsed.message_id == "<abc@clientco.com>"
    assert "update" in (parsed.body_text or "")


def test_parse_eml_missing_from_raises():
    raw = b"Subject: no sender\r\nDate: Mon, 10 Aug 2026 09:30:00 +0000\r\n\r\nBody\r\n"
    with pytest.raises(InvalidEmailError):
        parse_eml(raw)


def test_parse_eml_missing_date_raises():
    raw = b"From: a@b.com\r\nSubject: no date\r\n\r\nBody\r\n"
    with pytest.raises(InvalidEmailError):
        parse_eml(raw)


def test_parse_eml_cc_addresses():
    raw = (
        b"From: a@b.com\r\nTo: c@d.com\r\nCc: e@f.com, g@h.com\r\n"
        b"Subject: x\r\nDate: Mon, 10 Aug 2026 09:30:00 +0000\r\n\r\nBody\r\n"
    )
    parsed = parse_eml(raw)
    assert parsed.cc_addresses == ["e@f.com", "g@h.com"]


# ----------------------------------------------------------------- compute_direction_and_external ----


def test_compute_direction_outbound_internal_only():
    direction, is_external = compute_direction_and_external("alice@ourcompany.com", ["bob@ourcompany.com"], [], {"ourcompany.com"})
    assert direction.value == "outbound"
    assert is_external is False


def test_compute_direction_outbound_to_external():
    direction, is_external = compute_direction_and_external("alice@ourcompany.com", ["client@clientco.com"], [], {"ourcompany.com"})
    assert direction.value == "outbound"
    assert is_external is True


def test_compute_direction_inbound_from_external():
    direction, is_external = compute_direction_and_external("client@clientco.com", ["alice@ourcompany.com"], [], {"ourcompany.com"})
    assert direction.value == "inbound"
    assert is_external is True


def test_compute_direction_external_via_cc():
    direction, is_external = compute_direction_and_external(
        "alice@ourcompany.com", ["bob@ourcompany.com"], ["client@clientco.com"], {"ourcompany.com"}
    )
    assert direction.value == "outbound"
    assert is_external is True


# ------------------------------------------------------------------------------- ingest_email ----


def test_ingest_email_computes_direction_from_real_users(db_session):
    seed = _seed(db_session)
    record = ingest_email(
        db_session,
        EmailIngestData(
            task_id=seed["task"].id, from_address="alice@ourcompany.com", to_addresses=["client@clientco.com"],
            sent_at=datetime(2026, 8, 1, 9, 0),
        ),
    )
    assert record.direction.value == "outbound"
    assert record.is_external is True
    assert record.task_id == seed["task"].id


def test_ingest_email_inbound_from_client(db_session):
    seed = _seed(db_session)
    record = ingest_email(
        db_session,
        EmailIngestData(
            task_id=seed["task"].id, from_address="client@clientco.com", to_addresses=["alice@ourcompany.com"],
            sent_at=datetime(2026, 8, 3, 9, 0),
        ),
    )
    assert record.direction.value == "inbound"
    assert record.is_external is True


def test_ingest_email_duplicate_message_id_raises_integrity_error(db_session):
    seed = _seed(db_session)
    common_kwargs = dict(
        task_id=seed["task"].id, from_address="alice@ourcompany.com", to_addresses=["client@clientco.com"],
        sent_at=datetime(2026, 8, 1, 9, 0), message_id="<dup@ourcompany.com>",
    )
    ingest_email(db_session, EmailIngestData(**common_kwargs))
    with pytest.raises(IntegrityError):
        ingest_email(db_session, EmailIngestData(**common_kwargs))


def test_ingest_email_stores_addresses_as_comma_joined(db_session):
    seed = _seed(db_session)
    record = ingest_email(
        db_session,
        EmailIngestData(
            task_id=seed["task"].id, from_address="alice@ourcompany.com",
            to_addresses=["client@clientco.com", "other@clientco.com"], cc_addresses=["cc1@clientco.com"],
            sent_at=datetime(2026, 8, 1, 9, 0),
        ),
    )
    assert record.to_addresses == "client@clientco.com, other@clientco.com"
    assert record.cc_addresses == "cc1@clientco.com"
