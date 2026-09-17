"""DB-integration tests for app.services.import_export.importer.run_import — the full
parse -> map -> validate -> dedupe -> (insert) pipeline, exercised through real CSV bytes
against a seeded SQLite database. Covers the preview/commit symmetry, that invalid rows never
touch the database, duplicate detection at both levels, and the import_history audit log.
"""

import json

from app.models.enums import ProjectStatus, TaskStatus, UserRole
from app.models.import_history import ImportHistory
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.import_export.importer import run_import


def _seed(db_session):
    manager = User(name="Manager Import", email="mgr-import@example.com", role=UserRole.MANAGER, department="Engineering")
    alice = User(name="Alice Import", email="alice-import2@example.com", role=UserRole.EMPLOYEE, department="Engineering")
    db_session.add_all([manager, alice])
    db_session.commit()
    project = Project(name="Website Revamp", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    return {"manager": manager, "alice": alice, "project": project}


def _csv(rows: list[str]) -> bytes:
    header = "Employee,Task,Project,Priority,Estimated Hours,Start Date,Deadline,Status\n"
    return (header + "\n".join(rows) + "\n").encode("utf-8")


def test_preview_does_not_write_to_database(db_session):
    seed = _seed(db_session)
    content = _csv([f"Alice Import,Design homepage,{seed['project'].name},high,5,2026-08-01,2026-08-10,in_progress"])

    result = run_import(db_session, filename="tasks.csv", content=content, dry_run=True, imported_by=None)

    assert result.rows_processed == 1
    assert result.rows_accepted == 1
    assert result.rows_rejected == 0
    assert result.rows[0].status == "accepted"
    assert result.rows[0].task_id is None
    assert db_session.query(Task).count() == 0
    assert db_session.query(ImportHistory).count() == 0
    assert result.history_id is None


def test_commit_creates_tasks_and_history(db_session):
    seed = _seed(db_session)
    content = _csv([f"Alice Import,Design homepage,{seed['project'].name},high,5,2026-08-01,2026-08-10,in_progress"])

    result = run_import(db_session, filename="tasks.csv", content=content, dry_run=False, imported_by=seed["manager"].id)

    assert result.rows_accepted == 1
    assert result.rows[0].task_id is not None
    task = db_session.get(Task, result.rows[0].task_id)
    assert task.title == "Design homepage"
    assert task.assigned_to == seed["alice"].id
    assert task.project_id == seed["project"].id

    history = db_session.get(ImportHistory, result.history_id)
    assert history is not None
    assert history.filename == "tasks.csv"
    assert history.imported_by == seed["manager"].id
    assert history.rows_processed == 1
    assert history.rows_accepted == 1
    assert history.rows_rejected == 0


def test_commit_rejects_invalid_row_without_inserting(db_session):
    seed = _seed(db_session)
    content = _csv([f"Ghost Employee,Design homepage,{seed['project'].name},high,5,2026-08-01,2026-08-10,in_progress"])

    result = run_import(db_session, filename="tasks.csv", content=content, dry_run=False, imported_by=None)

    assert result.rows_accepted == 0
    assert result.rows_rejected == 1
    assert result.rows[0].status == "rejected"
    assert any("Unknown employee" in e for e in result.rows[0].errors)
    assert db_session.query(Task).count() == 0

    history = db_session.get(ImportHistory, result.history_id)
    assert history.rows_rejected == 1
    errors = json.loads(history.errors)
    assert errors[0]["row"] == 1
    assert any("Unknown employee" in e for e in errors[0]["errors"])


def test_commit_mixed_valid_and_invalid_rows(db_session):
    seed = _seed(db_session)
    content = _csv(
        [
            f"Alice Import,Good task,{seed['project'].name},high,5,2026-08-01,2026-08-10,in_progress",
            f"Ghost,Bad task,{seed['project'].name},high,5,,,",
        ]
    )

    result = run_import(db_session, filename="tasks.csv", content=content, dry_run=False, imported_by=None)

    assert result.rows_processed == 2
    assert result.rows_accepted == 1
    assert result.rows_rejected == 1
    assert db_session.query(Task).count() == 1


def test_duplicate_within_file_is_flagged(db_session):
    seed = _seed(db_session)
    row = f"Alice Import,Design homepage,{seed['project'].name},high,5,2026-08-01,,not_started"
    content = _csv([row, row])

    result = run_import(db_session, filename="tasks.csv", content=content, dry_run=False, imported_by=None)

    assert result.rows_accepted == 1
    assert result.rows_duplicate == 1
    assert result.rows_rejected == 1  # duplicates count as rejected in the summary total
    assert result.rows[1].status == "duplicate"
    assert db_session.query(Task).count() == 1


def test_duplicate_against_existing_database_row_is_skipped(db_session):
    seed = _seed(db_session)
    existing = Task(project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Design homepage", start_date=None)
    db_session.add(existing)
    db_session.commit()

    content = _csv([f"Alice Import,Design homepage,{seed['project'].name},high,5,,,"])
    result = run_import(db_session, filename="tasks.csv", content=content, dry_run=False, imported_by=None)

    assert result.rows_duplicate == 1
    assert result.rows[0].status == "duplicate"
    assert f"existing task #{existing.id}" in result.rows[0].errors[0]
    assert db_session.query(Task).count() == 1  # no second task created


def test_missing_required_column_is_a_file_level_error(db_session):
    content = b"Employee,Priority\nAlice Import,high\n"
    result = run_import(db_session, filename="bad.csv", content=content, dry_run=False, imported_by=None)

    assert result.file_error is not None
    assert "task" in result.file_error.lower()
    assert result.rows_processed == 0
    assert result.history_id is not None  # a failed commit attempt is still audited

    history = db_session.get(ImportHistory, result.history_id)
    assert history.rows_processed == 0
    errors = json.loads(history.errors)
    assert "file_error" in errors[0]


def test_preview_file_level_error_is_not_logged_to_history(db_session):
    content = b"Employee,Priority\nAlice Import,high\n"
    result = run_import(db_session, filename="bad.csv", content=content, dry_run=True, imported_by=None)

    assert result.file_error is not None
    assert result.history_id is None
    assert db_session.query(ImportHistory).count() == 0


def test_unassigned_employee_column_blank_is_fine(db_session):
    seed = _seed(db_session)
    content = _csv([f",Unassigned task,{seed['project'].name},medium,,,,"])

    result = run_import(db_session, filename="tasks.csv", content=content, dry_run=False, imported_by=None)

    assert result.rows_accepted == 1
    task = db_session.get(Task, result.rows[0].task_id)
    assert task.assigned_to is None


def test_import_history_error_log_is_capped(db_session):
    from app.services.import_export import constants

    seed = _seed(db_session)
    rows = [f"Ghost {i},Bad task {i},{seed['project'].name},high,,,," for i in range(200)]
    content = _csv(rows)

    result = run_import(db_session, filename="tasks.csv", content=content, dry_run=False, imported_by=None)

    history = db_session.get(ImportHistory, result.history_id)
    assert len(history.errors) <= constants.MAX_ERROR_LOG_CHARS
    assert result.rows_rejected == 200
