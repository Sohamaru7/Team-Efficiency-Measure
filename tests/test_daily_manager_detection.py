"""Unit tests for the Phase 10 additions to app.services.ai.detection: detect_quality_issues
and detect_project_risks. Both are additive — detect_issues() itself is untouched, verified by
re-running the existing Phase 7 suite unmodified (tests/test_ai_detection.py).
"""

from datetime import date, timedelta

from app.models.enums import ProjectStatus, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.ai.detection import detect_project_risks, detect_quality_issues


def _seed(db_session):
    manager = User(name="Manager DM", email="mgr-dm-detect@example.com", role=UserRole.MANAGER, department="Engineering")
    alice = User(name="Alice DM", email="alice-dm-detect@example.com", department="Engineering")
    db_session.add_all([manager, alice])
    db_session.commit()
    project = Project(name="DM Detect Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    return {"manager": manager, "alice": alice, "project": project}


# ------------------------------------------------------------------------ detect_quality_issues ----


def test_detect_quality_issues_flags_low_score(db_session):
    seed = _seed(db_session)
    db_session.add(Task(
        project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Sloppy work",
        status=TaskStatus.COMPLETED, completed_date=date(2026, 8, 1), quality_score=35,
    ))
    db_session.commit()

    findings = detect_quality_issues(db_session)
    assert len(findings) == 1
    assert findings[0]["quality_score"] == 35.0
    assert findings[0]["name"] == "Alice DM"


def test_detect_quality_issues_ignores_scores_at_or_above_threshold(db_session):
    seed = _seed(db_session)
    db_session.add(Task(
        project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Good work",
        status=TaskStatus.COMPLETED, completed_date=date(2026, 8, 1), quality_score=75,
    ))
    db_session.commit()

    assert detect_quality_issues(db_session) == []


def test_detect_quality_issues_ignores_unrated_completed_tasks(db_session):
    seed = _seed(db_session)
    db_session.add(Task(
        project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Unrated",
        status=TaskStatus.COMPLETED, completed_date=date(2026, 8, 1), quality_score=None,
    ))
    db_session.commit()

    assert detect_quality_issues(db_session) == []


def test_detect_quality_issues_ignores_incomplete_tasks(db_session):
    seed = _seed(db_session)
    db_session.add(Task(
        project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Still going",
        status=TaskStatus.IN_PROGRESS, quality_score=10,
    ))
    db_session.commit()

    assert detect_quality_issues(db_session) == []


def test_detect_quality_issues_sorted_lowest_first(db_session):
    seed = _seed(db_session)
    db_session.add_all([
        Task(project_id=seed["project"].id, assigned_to=seed["alice"].id, title="A", status=TaskStatus.COMPLETED, completed_date=date(2026, 8, 1), quality_score=50),
        Task(project_id=seed["project"].id, assigned_to=seed["alice"].id, title="B", status=TaskStatus.COMPLETED, completed_date=date(2026, 8, 1), quality_score=20),
    ])
    db_session.commit()

    findings = detect_quality_issues(db_session)
    assert [f["quality_score"] for f in findings] == [20.0, 50.0]


# ------------------------------------------------------------------------- detect_project_risks ----


def test_detect_project_risks_flags_near_deadline_low_progress(db_session):
    seed = _seed(db_session)
    today = date(2026, 8, 15)
    project = Project(name="At Risk Project", manager_id=seed["manager"].id, status=ProjectStatus.ACTIVE, deadline=today + timedelta(days=5))
    db_session.add(project)
    db_session.commit()
    db_session.add(Task(project_id=project.id, title="Not started", status=TaskStatus.NOT_STARTED, estimated_hours=10))
    db_session.commit()

    findings = detect_project_risks(db_session, as_of=str(today))
    assert len(findings) == 1
    assert findings[0]["project_id"] == project.id
    assert findings[0]["days_left"] == 5


def test_detect_project_risks_ignores_far_deadline(db_session):
    seed = _seed(db_session)
    today = date(2026, 8, 15)
    project = Project(name="Fine For Now", manager_id=seed["manager"].id, status=ProjectStatus.ACTIVE, deadline=today + timedelta(days=60))
    db_session.add(project)
    db_session.commit()
    db_session.add(Task(project_id=project.id, title="Not started", status=TaskStatus.NOT_STARTED))
    db_session.commit()

    assert detect_project_risks(db_session, as_of=str(today)) == []


def test_detect_project_risks_ignores_high_progress(db_session):
    seed = _seed(db_session)
    today = date(2026, 8, 15)
    project = Project(name="Almost Done", manager_id=seed["manager"].id, status=ProjectStatus.ACTIVE, deadline=today + timedelta(days=3))
    db_session.add(project)
    db_session.commit()
    db_session.add(Task(project_id=project.id, title="Done", status=TaskStatus.COMPLETED, completed_date=today))
    db_session.commit()

    assert detect_project_risks(db_session, as_of=str(today)) == []


def test_detect_project_risks_ignores_no_deadline(db_session):
    seed = _seed(db_session)
    project = Project(name="No Deadline", manager_id=seed["manager"].id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()

    assert detect_project_risks(db_session, as_of="2026-08-15") == []


def test_detect_project_risks_ignores_non_active_projects(db_session):
    seed = _seed(db_session)
    today = date(2026, 8, 15)
    project = Project(name="Planning Only", manager_id=seed["manager"].id, status=ProjectStatus.PLANNING, deadline=today + timedelta(days=2))
    db_session.add(project)
    db_session.commit()

    assert detect_project_risks(db_session, as_of=str(today)) == []
