"""DB-integration tests for app.services.emailing.delay_classification.classify_delay — the
Phase 9 headline feature: reuses the unmodified metrics.detect_delays formula, then adds an
optional explanation only when real linked-email evidence supports one.
"""

from datetime import date, datetime, timedelta

from app.models.email import Email
from app.models.enums import EmailDirection, ProjectStatus, TaskPriority, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.emailing.delay_classification import classify_delay


def _seed(db_session):
    manager = User(name="Manager Delay", email="mgr-delay@ourcompany.com", role=UserRole.MANAGER, department="Engineering")
    alice = User(name="Alice Delay", email="alice-delay@ourcompany.com", role=UserRole.EMPLOYEE, department="Engineering")
    db_session.add_all([manager, alice])
    db_session.commit()
    project = Project(name="Delay Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    return {"manager": manager, "alice": alice, "project": project}


def _delayed_task(db_session, seed, delay_reason=None):
    today = date(2026, 8, 20)
    task = Task(
        project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Ship feature",
        status=TaskStatus.IN_PROGRESS, priority=TaskPriority.HIGH,
        deadline=today - timedelta(days=10), delay_reason=delay_reason,
    )
    db_session.add(task)
    db_session.commit()
    return task


def test_not_delayed_task_returns_n_a(db_session):
    seed = _seed(db_session)
    task = Task(project_id=seed["project"].id, title="On track", status=TaskStatus.IN_PROGRESS, deadline=date(2026, 9, 1))
    db_session.add(task)
    db_session.commit()

    result = classify_delay(db_session, task, as_of=date(2026, 8, 20))
    assert result.is_delayed is False
    assert result.confidence == "n/a"
    assert result.delay_type is None


def test_delayed_with_no_emails_is_unclassified(db_session):
    seed = _seed(db_session)
    task = _delayed_task(db_session, seed, delay_reason="waiting for client")

    result = classify_delay(db_session, task, as_of=date(2026, 8, 20))
    assert result.is_delayed is True
    assert result.delay_type is None
    assert result.confidence == "none"
    assert result.duration_days is not None  # falls back to the existing detect_delays value


def test_client_response_delay_matches_brief_example(db_session):
    """The exact scenario from the Phase 9 brief: task delayed because "waiting for client",
    email evidence shows the client responded 2 days later -> External / Client response
    delay / 2 days.
    """
    seed = _seed(db_session)
    task = _delayed_task(db_session, seed, delay_reason="waiting for client")

    db_session.add_all([
        Email(
            task_id=task.id, from_address="alice-delay@ourcompany.com", to_addresses="client@clientco.com",
            direction=EmailDirection.OUTBOUND, is_external=True, sent_at=datetime(2026, 8, 10, 9, 0),
        ),
        Email(
            task_id=task.id, from_address="client@clientco.com", to_addresses="alice-delay@ourcompany.com",
            direction=EmailDirection.INBOUND, is_external=True, sent_at=datetime(2026, 8, 12, 9, 0),
        ),
    ])
    db_session.commit()

    result = classify_delay(db_session, task, as_of=date(2026, 8, 20))
    assert result.is_delayed is True
    assert result.delay_type == "external"
    assert result.cause == "Client response delay"
    assert result.duration_days == 2
    assert result.confidence == "high"  # delay_reason mentions "client"
    assert len(result.evidence_email_ids) == 2


def test_client_response_delay_confidence_medium_without_delay_reason_hint(db_session):
    seed = _seed(db_session)
    task = _delayed_task(db_session, seed, delay_reason=None)
    db_session.add_all([
        Email(
            task_id=task.id, from_address="alice-delay@ourcompany.com", to_addresses="client@clientco.com",
            direction=EmailDirection.OUTBOUND, is_external=True, sent_at=datetime(2026, 8, 10, 9, 0),
        ),
        Email(
            task_id=task.id, from_address="client@clientco.com", to_addresses="alice-delay@ourcompany.com",
            direction=EmailDirection.INBOUND, is_external=True, sent_at=datetime(2026, 8, 12, 9, 0),
        ),
    ])
    db_session.commit()

    result = classify_delay(db_session, task, as_of=date(2026, 8, 20))
    assert result.confidence == "medium"


def test_pending_response_signal_used_when_no_reply(db_session):
    seed = _seed(db_session)
    task = _delayed_task(db_session, seed)
    db_session.add(Email(
        task_id=task.id, from_address="alice-delay@ourcompany.com", to_addresses="client@clientco.com",
        direction=EmailDirection.OUTBOUND, is_external=True, sent_at=datetime(2026, 8, 15, 9, 0),
    ))
    db_session.commit()

    result = classify_delay(db_session, task, as_of=date(2026, 8, 20))
    assert result.delay_type == "external"
    assert result.cause == "Awaiting external response"
    assert result.duration_days == 5


def test_approval_delay_signal(db_session):
    seed = _seed(db_session)
    task = _delayed_task(db_session, seed)
    db_session.add_all([
        Email(
            task_id=task.id, from_address="alice-delay@ourcompany.com", to_addresses="client@clientco.com",
            subject="Please approve the design", direction=EmailDirection.OUTBOUND, is_external=True,
            sent_at=datetime(2026, 8, 10, 9, 0),
        ),
        Email(
            task_id=task.id, from_address="client@clientco.com", to_addresses="alice-delay@ourcompany.com",
            subject="Re: Please approve the design", direction=EmailDirection.INBOUND, is_external=True,
            sent_at=datetime(2026, 8, 15, 9, 0),
        ),
    ])
    db_session.commit()

    result = classify_delay(db_session, task, as_of=date(2026, 8, 20))
    assert result.cause == "Approval delay"
    assert result.duration_days == 5


def test_external_blocker_signal_used_as_last_resort(db_session):
    seed = _seed(db_session)
    task = _delayed_task(db_session, seed)
    db_session.add(Email(
        task_id=task.id, from_address="client@clientco.com", to_addresses="alice-delay@ourcompany.com",
        subject="We are blocked on legal review", direction=EmailDirection.INBOUND, is_external=True,
        sent_at=datetime(2026, 8, 5, 9, 0),
    ))
    db_session.commit()

    result = classify_delay(db_session, task, as_of=date(2026, 8, 20))
    assert result.cause == "External blocker mentioned"
    assert result.confidence == "low"


def test_internal_only_emails_do_not_produce_a_classification(db_session):
    seed = _seed(db_session)
    task = _delayed_task(db_session, seed)
    db_session.add(Email(
        task_id=task.id, from_address="alice-delay@ourcompany.com", to_addresses="mgr-delay@ourcompany.com",
        subject="Status check", direction=EmailDirection.OUTBOUND, is_external=False,
        sent_at=datetime(2026, 8, 15, 9, 0),
    ))
    db_session.commit()

    result = classify_delay(db_session, task, as_of=date(2026, 8, 20))
    assert result.delay_type is None
    assert result.confidence == "none"
    assert result.duration_days is not None  # existing detect_delays value still surfaced


def test_classify_delay_never_alters_detect_delays_value(db_session):
    """Cross-check that classify_delay's duration_days (when unclassified) matches the
    untouched metrics.detect_delays formula exactly -- proving no formula was modified.
    """
    from app.services.analytics.metrics import detect_delays

    seed = _seed(db_session)
    task = _delayed_task(db_session, seed)
    as_of = date(2026, 8, 20)

    expected = detect_delays([task], as_of=as_of)[0]
    result = classify_delay(db_session, task, as_of=as_of)

    assert result.duration_days == expected.delay_days
    assert result.is_delayed == expected.is_delayed
