"""API-level authorization boundary tests (production-readiness pass) — exercises the real
HTTP stack with `client_as` to authenticate as specific employees/managers/admins in different
departments, proving the brief's three access rules end-to-end:

- Employees must only access their own data.
- Managers can access their team's (same-department) data, not another team's.
- Admins can manage the system (everyone/everything).
"""

from datetime import date

from app.models.enums import ProjectStatus, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User


def _seed(db_session):
    admin = User(name="Admin", email="admin-authz@example.com", role=UserRole.ADMIN, department="Executive")
    eng_manager = User(name="Eng Manager", email="eng-mgr-authz@example.com", role=UserRole.MANAGER, department="Engineering")
    sales_manager = User(name="Sales Manager", email="sales-mgr-authz@example.com", role=UserRole.MANAGER, department="Sales")
    alice = User(name="Alice", email="alice-authz@example.com", role=UserRole.EMPLOYEE, department="Engineering")
    bob = User(name="Bob", email="bob-authz@example.com", role=UserRole.EMPLOYEE, department="Engineering")
    carol = User(name="Carol", email="carol-authz@example.com", role=UserRole.EMPLOYEE, department="Sales")
    db_session.add_all([admin, eng_manager, sales_manager, alice, bob, carol])
    db_session.commit()

    project = Project(name="Eng Project", manager_id=eng_manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()

    alice_task = Task(project_id=project.id, assigned_to=alice.id, title="Alice's task", status=TaskStatus.IN_PROGRESS)
    bob_task = Task(project_id=project.id, assigned_to=bob.id, title="Bob's task", status=TaskStatus.IN_PROGRESS)
    db_session.add_all([alice_task, bob_task])
    db_session.commit()

    return {
        "admin": admin, "eng_manager": eng_manager, "sales_manager": sales_manager,
        "alice": alice, "bob": bob, "carol": carol, "project": project,
        "alice_task": alice_task, "bob_task": bob_task,
    }


# ------------------------------------------------------------------------------------- users ----


def test_employee_can_view_own_profile_not_teammates(client_as, db_session):
    seed = _seed(db_session)
    own = client_as(seed["alice"]).get(f"/api/users/{seed['alice'].id}")
    assert own.status_code == 200

    other = client_as(seed["alice"]).get(f"/api/users/{seed['bob'].id}")
    assert other.status_code == 403


def test_manager_can_view_team_not_other_department(client_as, db_session):
    seed = _seed(db_session)
    same_team = client_as(seed["eng_manager"]).get(f"/api/users/{seed['alice'].id}")
    assert same_team.status_code == 200

    other_team = client_as(seed["eng_manager"]).get(f"/api/users/{seed['carol'].id}")
    assert other_team.status_code == 403


def test_admin_can_view_anyone(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["admin"]).get(f"/api/users/{seed['carol'].id}")
    assert resp.status_code == 200


def test_employee_cannot_escalate_own_role(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).patch(f"/api/users/{seed['alice'].id}", json={"role": "admin"})
    assert resp.status_code == 403


def test_employee_can_edit_own_name(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).patch(f"/api/users/{seed['alice'].id}", json={"name": "Alice Renamed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Alice Renamed"


def test_employee_cannot_create_users(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).post(
        "/api/users", json={"name": "New", "email": "new@example.com", "password": "correcthorse1"}
    )
    assert resp.status_code == 403


def test_manager_cannot_create_users_only_admin_can(client_as, db_session):
    seed = _seed(db_session)
    manager_attempt = client_as(seed["eng_manager"]).post(
        "/api/users", json={"name": "New", "email": "new2@example.com", "password": "correcthorse1"}
    )
    assert manager_attempt.status_code == 403

    admin_attempt = client_as(seed["admin"]).post(
        "/api/users", json={"name": "New", "email": "new3@example.com", "password": "correcthorse1"}
    )
    assert admin_attempt.status_code == 201


def test_only_admin_can_delete_a_user(client_as, db_session):
    seed = _seed(db_session)
    manager_attempt = client_as(seed["eng_manager"]).delete(f"/api/users/{seed['bob'].id}")
    assert manager_attempt.status_code == 403

    admin_attempt = client_as(seed["admin"]).delete(f"/api/users/{seed['bob'].id}")
    assert admin_attempt.status_code == 204


def test_list_users_scoped_to_department_for_manager(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["eng_manager"]).get("/api/users")
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert "alice-authz@example.com" in emails
    assert "carol-authz@example.com" not in emails


def test_list_users_forbidden_for_employee(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).get("/api/users")
    assert resp.status_code == 403


# ------------------------------------------------------------------------------------- tasks ----


def test_employee_sees_only_own_tasks_in_list(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).get("/api/tasks")
    assert resp.status_code == 200
    titles = {t["title"] for t in resp.json()}
    assert titles == {"Alice's task"}


def test_employee_cannot_view_teammates_task_detail(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).get(f"/api/tasks/{seed['bob_task'].id}")
    assert resp.status_code == 403


def test_manager_sees_teams_tasks_not_other_departments(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["eng_manager"]).get("/api/tasks")
    assert resp.status_code == 200
    titles = {t["title"] for t in resp.json()}
    assert titles == {"Alice's task", "Bob's task"}


def test_employee_can_create_task_for_self_not_others(client_as, db_session):
    seed = _seed(db_session)
    own = client_as(seed["alice"]).post(
        "/api/tasks", json={"project_id": seed["project"].id, "title": "Self task", "assigned_to": seed["alice"].id}
    )
    assert own.status_code == 201

    for_other = client_as(seed["alice"]).post(
        "/api/tasks", json={"project_id": seed["project"].id, "title": "Sneaky task", "assigned_to": seed["bob"].id}
    )
    assert for_other.status_code == 403


def test_employee_cannot_delete_own_task_manager_can(client_as, db_session):
    seed = _seed(db_session)
    employee_attempt = client_as(seed["alice"]).delete(f"/api/tasks/{seed['alice_task'].id}")
    assert employee_attempt.status_code == 403

    manager_attempt = client_as(seed["eng_manager"]).delete(f"/api/tasks/{seed['alice_task'].id}")
    assert manager_attempt.status_code == 204


def test_changed_by_is_always_the_authenticated_caller_not_a_client_supplied_id(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).patch(
        f"/api/tasks/{seed['alice_task'].id}", json={"status": "completed", "changed_by": seed["eng_manager"].id}
    )
    assert resp.status_code == 200

    from app.models.task_history import TaskHistory

    history = db_session.query(TaskHistory).filter_by(task_id=seed["alice_task"].id).order_by(TaskHistory.id.desc()).first()
    assert history.changed_by == seed["alice"].id
    assert history.changed_by != seed["eng_manager"].id


# ---------------------------------------------------------------------------- daily updates ----


def test_employee_cannot_submit_daily_update_for_someone_else(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).post(
        "/api/daily-updates", json={"user_id": seed["bob"].id, "date": str(date.today()), "tasks_completed": 1, "tasks_pending": 0}
    )
    assert resp.status_code == 403


def test_manager_cannot_edit_teammates_daily_update(client_as, db_session):
    seed = _seed(db_session)
    created = client_as(seed["alice"]).post(
        "/api/daily-updates", json={"user_id": seed["alice"].id, "date": str(date.today()), "tasks_completed": 1, "tasks_pending": 0}
    )
    update_id = created.json()["id"]

    manager_view = client_as(seed["eng_manager"]).get(f"/api/daily-updates/{update_id}")
    assert manager_view.status_code == 200  # managers can read their team's

    manager_edit = client_as(seed["eng_manager"]).patch(f"/api/daily-updates/{update_id}", json={"tasks_completed": 5})
    assert manager_edit.status_code == 403  # but never write someone else's self-report


# -------------------------------------------------------------------------- manager-only surfaces ----


def test_dashboard_requires_manager_or_admin(client_as, db_session):
    seed = _seed(db_session)
    employee_attempt = client_as(seed["alice"]).get("/api/dashboard")
    assert employee_attempt.status_code == 403

    manager_attempt = client_as(seed["eng_manager"]).get("/api/dashboard")
    assert manager_attempt.status_code == 200


def test_manager_dashboard_forbidden_for_other_departments_employee_filter(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["eng_manager"]).get("/api/dashboard", params={"employee_id": seed["carol"].id})
    assert resp.status_code == 403


def test_ai_assistant_requires_manager_or_admin(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).post("/api/ai/ask", json={"question": "How is my team doing?"})
    assert resp.status_code == 403


def test_daily_manager_requires_manager_or_admin(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).post("/api/daily-manager/run")
    assert resp.status_code == 403


def test_import_export_require_manager_or_admin(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["alice"]).get("/api/import/history")
    assert resp.status_code == 403
    resp2 = client_as(seed["alice"]).get("/api/export/tasks")
    assert resp2.status_code == 403


def test_team_score_restricted_to_own_department_for_manager(client_as, db_session):
    seed = _seed(db_session)
    resp = client_as(seed["eng_manager"]).get("/api/analytics/team/score", params={"user_ids": [seed["carol"].id]})
    assert resp.status_code == 403

    resp_ok = client_as(seed["eng_manager"]).get("/api/analytics/team/score", params={"user_ids": [seed["alice"].id]})
    assert resp_ok.status_code == 200


# -------------------------------------------------------------------------------- unauthenticated ----


def test_every_protected_surface_401s_with_no_token(unauthenticated_client):
    for method, path in [
        ("get", "/api/users"), ("get", "/api/tasks"), ("get", "/api/dashboard"),
        ("get", "/api/daily-manager/reports"), ("get", "/api/import/history"),
    ]:
        resp = getattr(unauthenticated_client, method)(path)
        assert resp.status_code == 401, f"{method.upper()} {path} should require authentication"
