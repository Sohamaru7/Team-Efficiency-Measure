"""Unit tests for app.services.authz — the pure role/ownership predicates every route depends
on (directly or via app.api.deps.require_roles). No FastAPI, no HTTP — just the rules
themselves, so they're testable in complete isolation from the auth/HTTP layer (see
tests/test_authorization_boundaries.py for the end-to-end API-level tests).
"""

from app.models.daily_update import DailyUpdate
from app.models.enums import UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services import authz


def _user(id_, role=UserRole.EMPLOYEE, department="Engineering"):
    return User(id=id_, name=f"User {id_}", email=f"user{id_}@example.com", role=role, department=department)


# ------------------------------------------------------------------------------------- users ----


def test_admin_can_view_anyone():
    admin = _user(1, UserRole.ADMIN, department="Anywhere")
    other = _user(2, department="Elsewhere")
    assert authz.can_view_user(admin, other) is True


def test_self_can_view_self():
    alice = _user(1)
    assert authz.can_view_user(alice, alice) is True


def test_manager_can_view_same_department():
    manager = _user(1, UserRole.MANAGER, department="Engineering")
    teammate = _user(2, department="Engineering")
    assert authz.can_view_user(manager, teammate) is True


def test_manager_cannot_view_other_department():
    manager = _user(1, UserRole.MANAGER, department="Engineering")
    other = _user(2, department="Sales")
    assert authz.can_view_user(manager, other) is False


def test_employee_cannot_view_another_employee():
    alice = _user(1, department="Engineering")
    bob = _user(2, department="Engineering")
    assert authz.can_view_user(alice, bob) is False


def test_manager_with_no_department_has_no_team():
    manager = _user(1, UserRole.MANAGER, department=None)
    other = _user(2, department=None)
    assert authz.can_view_user(manager, other) is False  # fails closed, not open


def test_self_can_modify_own_name_and_email_only():
    alice = _user(1)
    assert authz.can_modify_user(alice, alice, {"name"}) is True
    assert authz.can_modify_user(alice, alice, {"email"}) is True


def test_self_cannot_escalate_own_role_or_active_or_password():
    alice = _user(1)
    assert authz.can_modify_user(alice, alice, {"role"}) is False
    assert authz.can_modify_user(alice, alice, {"active"}) is False
    assert authz.can_modify_user(alice, alice, {"password"}) is False
    assert authz.can_modify_user(alice, alice, {"name", "role"}) is False  # any disallowed field blocks the whole edit


def test_admin_can_modify_anyone_any_field():
    admin = _user(1, UserRole.ADMIN)
    other = _user(2)
    assert authz.can_modify_user(admin, other, {"role", "active", "password"}) is True


def test_manager_cannot_modify_teammate():
    manager = _user(1, UserRole.MANAGER, department="Engineering")
    teammate = _user(2, department="Engineering")
    assert authz.can_modify_user(manager, teammate, {"name"}) is False


def test_only_admin_can_delete_user():
    assert authz.can_delete_user(_user(1, UserRole.ADMIN)) is True
    assert authz.can_delete_user(_user(1, UserRole.MANAGER)) is False
    assert authz.can_delete_user(_user(1, UserRole.EMPLOYEE)) is False


# ------------------------------------------------------------------------------------- tasks ----


def _task(assigned_to=None, assignee=None, project=None):
    t = Task(id=1, project_id=1, assigned_to=assigned_to, title="T")
    t.assignee = assignee
    t.project = project
    return t


def test_employee_can_view_own_task():
    alice = _user(1)
    task = _task(assigned_to=1)
    assert authz.can_view_task(alice, task) is True


def test_employee_cannot_view_others_task():
    alice = _user(1)
    task = _task(assigned_to=2)
    assert authz.can_view_task(alice, task) is False


def test_manager_can_view_teammates_task():
    manager = _user(1, UserRole.MANAGER, department="Engineering")
    teammate = _user(2, department="Engineering")
    task = _task(assigned_to=2, assignee=teammate)
    assert authz.can_view_task(manager, task) is True


def test_manager_can_view_task_in_their_managed_project_even_if_other_department():
    manager = _user(1, UserRole.MANAGER, department="Engineering")
    other_dept_employee = _user(2, department="Sales")
    project = Project(id=1, name="P", manager_id=1)
    task = _task(assigned_to=2, assignee=other_dept_employee, project=project)
    assert authz.can_view_task(manager, task) is True


def test_manager_cannot_view_unrelated_task():
    manager = _user(1, UserRole.MANAGER, department="Engineering")
    other_dept_employee = _user(2, department="Sales")
    other_project = Project(id=2, name="P2", manager_id=99)
    task = _task(assigned_to=2, assignee=other_dept_employee, project=other_project)
    assert authz.can_view_task(manager, task) is False


def test_employee_self_service_creation_only_for_self():
    alice = _user(1)
    assert authz.can_create_task_for(alice, None) is True
    assert authz.can_create_task_for(alice, 1) is True
    assert authz.can_create_task_for(alice, 2) is False


def test_manager_can_create_task_for_anyone():
    manager = _user(1, UserRole.MANAGER)
    assert authz.can_create_task_for(manager, 999) is True


def test_employee_cannot_delete_own_task():
    alice = _user(1)
    task = _task(assigned_to=1, assignee=alice)
    assert authz.can_delete_task(alice, task) is False


def test_manager_can_delete_teammates_task():
    manager = _user(1, UserRole.MANAGER, department="Engineering")
    teammate = _user(2, department="Engineering")
    task = _task(assigned_to=2, assignee=teammate)
    assert authz.can_delete_task(manager, task) is True


def test_admin_can_delete_any_task():
    admin = _user(1, UserRole.ADMIN)
    task = _task(assigned_to=999)
    assert authz.can_delete_task(admin, task) is True


# ------------------------------------------------------------------------------ daily updates ----


def _daily_update(user_id, user=None):
    du = DailyUpdate(id=1, user_id=user_id)
    du.user = user
    return du


def test_employee_can_view_and_modify_own_daily_update():
    alice = _user(1)
    du = _daily_update(1, alice)
    assert authz.can_view_daily_update(alice, du) is True
    assert authz.can_modify_daily_update(alice, du) is True


def test_manager_can_view_but_not_modify_teammates_daily_update():
    manager = _user(1, UserRole.MANAGER, department="Engineering")
    teammate = _user(2, department="Engineering")
    du = _daily_update(2, teammate)
    assert authz.can_view_daily_update(manager, du) is True
    assert authz.can_modify_daily_update(manager, du) is False


def test_employee_cannot_view_others_daily_update():
    alice = _user(1)
    bob = _user(2)
    du = _daily_update(2, bob)
    assert authz.can_view_daily_update(alice, du) is False


def test_can_create_daily_update_for_self_only():
    alice = _user(1)
    assert authz.can_create_daily_update_for(alice, 1) is True
    assert authz.can_create_daily_update_for(alice, 2) is False


# ---------------------------------------------------------------------------------- projects ----


def test_manager_and_admin_can_view_any_project():
    assert authz.can_view_project(_user(1, UserRole.MANAGER)) is True
    assert authz.can_view_project(_user(1, UserRole.ADMIN)) is True


def test_employee_can_view_project_only_if_has_task_in_it():
    alice = _user(1)
    assert authz.can_view_project(alice, has_task_in_project=True) is True
    assert authz.can_view_project(alice, has_task_in_project=False) is False


def test_only_projects_own_manager_or_admin_can_modify():
    project = Project(id=1, name="P", manager_id=5)
    assert authz.can_modify_project(_user(5, UserRole.MANAGER), project) is True
    assert authz.can_modify_project(_user(6, UserRole.MANAGER), project) is False
    assert authz.can_modify_project(_user(99, UserRole.ADMIN), project) is True
