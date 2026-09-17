"""Unit tests for app.services.daily_manager.snapshot's severity functions and
build_issue_snapshot's DB-integration composition.
"""

from datetime import date, timedelta

from app.models.enums import ProjectStatus, TaskPriority, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.daily_manager.snapshot import (
    _delay_severity,
    _deadline_risk_severity,
    _imbalance_severity,
    _overloaded_severity,
    _performance_drop_severity,
    _project_risk_severity,
    _quality_severity,
    _recurring_severity,
    _underutilized_severity,
    build_issue_snapshot,
)


def test_overloaded_severity_thresholds():
    assert _overloaded_severity(101) == "low"
    assert _overloaded_severity(121) == "medium"
    assert _overloaded_severity(151) == "high"


def test_underutilized_severity_thresholds():
    assert _underutilized_severity(25) == "low"
    assert _underutilized_severity(15) == "medium"
    assert _underutilized_severity(5) == "high"


def test_imbalance_severity_thresholds():
    assert _imbalance_severity(55) == "low"
    assert _imbalance_severity(70) == "medium"
    assert _imbalance_severity(85) == "high"


def test_deadline_risk_severity():
    assert _deadline_risk_severity("high") == "high"
    assert _deadline_risk_severity("medium") == "medium"


def test_delay_severity_thresholds():
    assert _delay_severity(3) == "low"
    assert _delay_severity(10) == "medium"
    assert _delay_severity(20) == "high"
    assert _delay_severity(None) == "low"


def test_performance_drop_severity_thresholds():
    assert _performance_drop_severity(16) == "low"
    assert _performance_drop_severity(25) == "medium"
    assert _performance_drop_severity(35) == "high"


def test_recurring_severity_thresholds():
    assert _recurring_severity(2) == "low"
    assert _recurring_severity(3) == "medium"
    assert _recurring_severity(5) == "high"


def test_quality_severity_thresholds():
    assert _quality_severity(55) == "low"
    assert _quality_severity(45) == "medium"
    assert _quality_severity(35) == "high"


def test_project_risk_severity_thresholds():
    assert _project_risk_severity(10) == "low"
    assert _project_risk_severity(5) == "medium"
    assert _project_risk_severity(2) == "high"


def _seed(db_session):
    manager = User(name="Manager Snap", email="mgr-snap@example.com", role=UserRole.MANAGER, department="Engineering")
    alice = User(name="Alice Snap", email="alice-snap@example.com", department="Engineering")
    bob = User(name="Bob Snap", email="bob-snap@example.com", department="Engineering")
    db_session.add_all([manager, alice, bob])
    db_session.commit()
    project = Project(name="Snap Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    return {"manager": manager, "alice": alice, "bob": bob, "project": project}


def test_build_issue_snapshot_includes_overload_and_quality_and_project_risk(db_session):
    seed = _seed(db_session)
    today = date(2026, 8, 15)

    # Alice: heavily overloaded.
    for i in range(5):
        db_session.add(Task(
            project_id=seed["project"].id, assigned_to=seed["alice"].id, title=f"Alice task {i}",
            status=TaskStatus.IN_PROGRESS, priority=TaskPriority.HIGH, estimated_hours=20,
        ))
    # A low-quality completed task.
    db_session.add(Task(
        project_id=seed["project"].id, assigned_to=seed["bob"].id, title="Bad work",
        status=TaskStatus.COMPLETED, completed_date=today, quality_score=30,
    ))
    db_session.commit()

    # A near-deadline, low-progress project.
    risky_project = Project(name="Risky", manager_id=seed["manager"].id, status=ProjectStatus.ACTIVE, deadline=today + timedelta(days=3))
    db_session.add(risky_project)
    db_session.commit()
    db_session.add(Task(project_id=risky_project.id, title="Not started", status=TaskStatus.NOT_STARTED))
    db_session.commit()

    findings = build_issue_snapshot(db_session, today)
    issue_types = {f.issue_type for f in findings}
    assert "overloaded_employee" in issue_types
    assert "quality_issue" in issue_types
    assert "project_risk" in issue_types

    quality_finding = next(f for f in findings if f.issue_type == "quality_issue")
    assert quality_finding.severity == "high"  # 30 < QUALITY_HIGH_MAX_SCORE (40)

    project_finding = next(f for f in findings if f.issue_type == "project_risk")
    assert project_finding.severity == "high"  # 3 days left <= PROJECT_RISK_HIGH_DAYS


def test_build_issue_snapshot_empty_when_nothing_wrong(db_session):
    # Zero workload counts as "underutilized" under Phase 7's own unchanged threshold, so give
    # everyone a normal-range (30-100%) workload -- the actual "nothing wrong" baseline.
    seed = _seed(db_session)
    for user in (seed["manager"], seed["alice"], seed["bob"]):
        db_session.add(Task(
            project_id=seed["project"].id, assigned_to=user.id, title=f"Normal task for {user.name}",
            status=TaskStatus.IN_PROGRESS, estimated_hours=20,
        ))
    db_session.commit()

    findings = build_issue_snapshot(db_session, date(2026, 8, 15))
    assert findings == []
