"""DB-integration tests for app.services.emailing.permissions — the Phase 9 privacy control
gating who may see one email's content or a task's derived signals.
"""

from datetime import datetime

from app.models.email import Email
from app.models.enums import EmailDirection, ProjectStatus, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.emailing.permissions import can_view_email_content, can_view_task_or_project_emails


def _seed(db_session):
    manager = User(name="Manager Perm", email="mgr-perm@ourcompany.com", role=UserRole.MANAGER, department="Engineering")
    admin = User(name="Admin Perm", email="admin-perm@ourcompany.com", role=UserRole.ADMIN, department="Engineering")
    alice = User(name="Alice Perm", email="alice-perm@ourcompany.com", role=UserRole.EMPLOYEE, department="Engineering")
    bob = User(name="Bob Perm", email="bob-perm@ourcompany.com", role=UserRole.EMPLOYEE, department="Engineering")
    db_session.add_all([manager, admin, alice, bob])
    db_session.commit()
    project = Project(name="Perm Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    task = Task(project_id=project.id, assigned_to=alice.id, title="Task", status=TaskStatus.IN_PROGRESS)
    db_session.add(task)
    db_session.commit()
    email_row = Email(
        task_id=task.id, project_id=project.id, from_address="alice-perm@ourcompany.com",
        to_addresses="client@clientco.com", direction=EmailDirection.OUTBOUND, is_external=True,
        sent_at=datetime(2026, 8, 1, 9, 0),
    )
    db_session.add(email_row)
    db_session.commit()
    return {"manager": manager, "admin": admin, "alice": alice, "bob": bob, "project": project, "task": task, "email": email_row}


def test_none_requesting_user_id_denied(db_session):
    seed = _seed(db_session)
    assert can_view_email_content(db_session, seed["email"], None) is False


def test_unknown_requesting_user_id_denied(db_session):
    seed = _seed(db_session)
    assert can_view_email_content(db_session, seed["email"], 999999) is False


def test_manager_role_always_permitted(db_session):
    seed = _seed(db_session)
    assert can_view_email_content(db_session, seed["email"], seed["manager"].id) is True


def test_admin_role_always_permitted(db_session):
    seed = _seed(db_session)
    assert can_view_email_content(db_session, seed["email"], seed["admin"].id) is True


def test_task_assignee_permitted(db_session):
    seed = _seed(db_session)
    assert can_view_email_content(db_session, seed["email"], seed["alice"].id) is True


def test_unrelated_employee_denied(db_session):
    seed = _seed(db_session)
    assert can_view_email_content(db_session, seed["email"], seed["bob"].id) is False


def test_project_manager_permitted_via_project_id_only(db_session):
    seed = _seed(db_session)
    email_row = Email(
        project_id=seed["project"].id, from_address="client@clientco.com", to_addresses="mgr-perm@ourcompany.com",
        direction=EmailDirection.INBOUND, is_external=True, sent_at=datetime(2026, 8, 1, 9, 0),
    )
    db_session.add(email_row)
    db_session.commit()
    assert can_view_email_content(db_session, email_row, seed["manager"].id) is True
    assert can_view_email_content(db_session, email_row, seed["bob"].id) is False


def test_can_view_task_or_project_emails_by_task_id(db_session):
    seed = _seed(db_session)
    assert can_view_task_or_project_emails(db_session, task_id=seed["task"].id, project_id=None, requesting_user_id=seed["alice"].id) is True
    assert can_view_task_or_project_emails(db_session, task_id=seed["task"].id, project_id=None, requesting_user_id=seed["bob"].id) is False
