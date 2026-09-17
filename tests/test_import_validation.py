"""Unit tests for app.services.import_export.validation and .duplicates. Uses real User/Project
rows (validation resolves Employee/Project by name against caches the caller builds), but the
validation function itself takes plain dicts/caches — no session queries happen inside it.
"""

from datetime import date
from decimal import Decimal

from app.models.enums import ProjectStatus, TaskPriority, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.import_export.duplicates import dedupe_key, find_existing_duplicate
from app.services.import_export.validation import validate_row


def _seed(db_session):
    alice = User(name="Alice Import", email="alice-import@example.com", role=UserRole.EMPLOYEE, department="Engineering")
    db_session.add(alice)
    db_session.commit()
    project = Project(name="Website Revamp", manager_id=None, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    return {"alice": alice, "project": project}


def _caches(db_session, seed):
    return {seed["project"].name.lower(): seed["project"]}, {seed["alice"].name.lower(): seed["alice"]}


def test_validate_row_happy_path(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    mapped = {
        "employee": "Alice Import",
        "task": "Design homepage",
        "project": "Website Revamp",
        "priority": "high",
        "estimated_hours": "5",
        "actual_hours": "",
        "start_date": "2026-08-01",
        "deadline": "2026-08-10",
        "status": "in_progress",
        "quality": "",
        "delay_reason": "",
    }
    result = validate_row(mapped, projects, users)
    assert result.errors == []
    assert result.task_kwargs["project_id"] == seed["project"].id
    assert result.task_kwargs["assigned_to"] == seed["alice"].id
    assert result.task_kwargs["title"] == "Design homepage"
    assert result.task_kwargs["priority"] == TaskPriority.HIGH
    assert result.task_kwargs["estimated_hours"] == Decimal("5")
    assert result.task_kwargs["start_date"] == date(2026, 8, 1)
    assert result.task_kwargs["deadline"] == date(2026, 8, 10)
    assert result.task_kwargs["status"] == TaskStatus.IN_PROGRESS


def test_validate_row_missing_required_fields(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row({"employee": "", "task": "", "project": ""}, projects, users)
    assert "Project is required" in result.errors
    assert "Task is required" in result.errors
    assert result.task_kwargs is None


def test_validate_row_unknown_project(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row({"task": "X", "project": "Nonexistent Project"}, projects, users)
    assert any("Unknown project" in e for e in result.errors)


def test_validate_row_unknown_employee(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row({"task": "X", "project": "Website Revamp", "employee": "Nobody"}, projects, users)
    assert any("Unknown employee" in e for e in result.errors)


def test_validate_row_blank_employee_is_unassigned_not_an_error(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row({"task": "X", "project": "Website Revamp", "employee": ""}, projects, users)
    assert result.errors == []
    assert result.task_kwargs["assigned_to"] is None


def test_validate_row_defaults_priority_and_status(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row({"task": "X", "project": "Website Revamp"}, projects, users)
    assert result.task_kwargs["priority"] == TaskPriority.MEDIUM
    assert result.task_kwargs["status"] == TaskStatus.NOT_STARTED


def test_validate_row_invalid_priority(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row({"task": "X", "project": "Website Revamp", "priority": "urgentish"}, projects, users)
    assert any("Priority" in e for e in result.errors)


def test_validate_row_priority_accepts_spaced_status_value(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row({"task": "X", "project": "Website Revamp", "status": "In Progress"}, projects, users)
    assert result.task_kwargs["status"] == TaskStatus.IN_PROGRESS


def test_validate_row_invalid_number(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row({"task": "X", "project": "Website Revamp", "estimated_hours": "not-a-number"}, projects, users)
    assert any("Estimated Hours" in e for e in result.errors)


def test_validate_row_negative_hours_rejected(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row({"task": "X", "project": "Website Revamp", "estimated_hours": "-5"}, projects, users)
    assert any("Estimated Hours" in e for e in result.errors)


def test_validate_row_quality_out_of_range(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row({"task": "X", "project": "Website Revamp", "quality": "150"}, projects, users)
    assert any("Quality" in e for e in result.errors)


def test_validate_row_invalid_date(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row({"task": "X", "project": "Website Revamp", "start_date": "not a date"}, projects, users)
    assert any("Start Date" in e for e in result.errors)


def test_validate_row_us_date_format_accepted(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row({"task": "X", "project": "Website Revamp", "start_date": "08/01/2026"}, projects, users)
    assert result.task_kwargs["start_date"] == date(2026, 8, 1)


def test_validate_row_deadline_before_start_date(db_session):
    seed = _seed(db_session)
    projects, users = _caches(db_session, seed)
    result = validate_row(
        {"task": "X", "project": "Website Revamp", "start_date": "2026-08-10", "deadline": "2026-08-01"}, projects, users
    )
    assert any("Deadline must be on or after Start Date" in e for e in result.errors)


# ---------------------------------------------------------------------------------- duplicates ----


def test_dedupe_key_ignores_case_and_whitespace():
    kwargs_a = {"project_id": 1, "assigned_to": 2, "title": " Design Homepage ", "start_date": date(2026, 8, 1)}
    kwargs_b = {"project_id": 1, "assigned_to": 2, "title": "design homepage", "start_date": date(2026, 8, 1)}
    assert dedupe_key(kwargs_a) == dedupe_key(kwargs_b)


def test_find_existing_duplicate_matches(db_session):
    seed = _seed(db_session)
    task = Task(project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Design homepage", start_date=date(2026, 8, 1))
    db_session.add(task)
    db_session.commit()

    match = find_existing_duplicate(
        db_session,
        {"project_id": seed["project"].id, "assigned_to": seed["alice"].id, "title": "design homepage", "start_date": date(2026, 8, 1)},
    )
    assert match is not None
    assert match.id == task.id


def test_find_existing_duplicate_no_match_different_start_date(db_session):
    seed = _seed(db_session)
    task = Task(project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Design homepage", start_date=date(2026, 8, 1))
    db_session.add(task)
    db_session.commit()

    match = find_existing_duplicate(
        db_session,
        {"project_id": seed["project"].id, "assigned_to": seed["alice"].id, "title": "design homepage", "start_date": date(2026, 9, 1)},
    )
    assert match is None


def test_find_existing_duplicate_unassigned_matches_unassigned_only(db_session):
    seed = _seed(db_session)
    task = Task(project_id=seed["project"].id, assigned_to=None, title="Unassigned task", start_date=None)
    db_session.add(task)
    db_session.commit()

    match = find_existing_duplicate(
        db_session, {"project_id": seed["project"].id, "assigned_to": None, "title": "Unassigned task", "start_date": None}
    )
    assert match is not None

    no_match = find_existing_duplicate(
        db_session,
        {"project_id": seed["project"].id, "assigned_to": seed["alice"].id, "title": "Unassigned task", "start_date": None},
    )
    assert no_match is None
