"""Role-based + ownership authorization rules (production-readiness pass). Every function here
is a pure predicate over already-loaded ORM objects — no DB queries, no FastAPI — so the rules
themselves are fully unit-testable in isolation from the HTTP layer (see
`tests/test_authz.py`). `app.api.deps` wraps these as FastAPI dependencies/guards; route
handlers call the predicates directly wherever a decision depends on the specific resource
being accessed (a single task, a single user, ...), since FastAPI dependencies alone can't see
the path-resolved object before the handler runs.

Three roles, per the brief:
- **Employee** — only their own data.
- **Manager** — their own data, plus their *team's* (defined consistently with every other
  phase of this app: same `User.department` — the same grouping `get_manager_dashboard`,
  `detect_issues`, etc. already use as "team").
- **Admin** — manages the system: full read/write on users, and the same team-scoped view as a
  manager would need is a strict subset of "everything," so admin checks are simply "always
  allowed" throughout this module.
"""

from __future__ import annotations

from app.models.daily_update import DailyUpdate
from app.models.enums import UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User


def is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


def is_manager(user: User) -> bool:
    return user.role == UserRole.MANAGER


def is_manager_or_admin(user: User) -> bool:
    return user.role in (UserRole.MANAGER, UserRole.ADMIN)


def same_team(manager: User, other: User) -> bool:
    """"Team" = same department. A manager with no department set has no team (fails closed,
    not open) — an unconfigured department is not license to see everyone.
    """
    return manager.department is not None and manager.department == other.department


# ------------------------------------------------------------------------------------- users ----


def can_view_user(current: User, target: User) -> bool:
    if is_admin(current) or current.id == target.id:
        return True
    return is_manager(current) and same_team(current, target)


_SELF_EDITABLE_FIELDS = frozenset({"name", "email"})


def can_modify_user(current: User, target: User, changed_fields: set[str]) -> bool:
    """`changed_fields` is the set of fields actually present in the update payload
    (`exclude_unset` semantics) — self-service edits are restricted to a safe subset so an
    employee can never grant themselves a role/active/password change via their own profile
    edit (privilege escalation), even though they're allowed to view+edit their own record.
    """
    if is_admin(current):
        return True
    if current.id == target.id:
        return changed_fields <= _SELF_EDITABLE_FIELDS
    return False


def can_delete_user(current: User) -> bool:
    return is_admin(current)


def can_list_all_users(current: User) -> bool:
    return is_admin(current)


# ------------------------------------------------------------------------------------- tasks ----


def can_view_task(current: User, task: Task) -> bool:
    if is_admin(current) or task.assigned_to == current.id:
        return True
    if not is_manager(current):
        return False
    if task.assignee is not None and same_team(current, task.assignee):
        return True
    return task.project is not None and task.project.manager_id == current.id


def can_modify_task(current: User, task: Task) -> bool:
    # Same rule as viewing: the assignee can update their own task's progress, a manager can
    # update their team's or their project's tasks, admin can update anything.
    return can_view_task(current, task)


def can_delete_task(current: User, task: Task) -> bool:
    # Deletion is deliberately narrower than view/modify: an employee may not delete their own
    # task (only update its progress) — data deletion is a manager/admin action throughout this
    # app (consistent with Phase 10's "deletion of data requires a human with real authority").
    if is_admin(current):
        return True
    if not is_manager(current):
        return False
    if task.assignee is not None and same_team(current, task.assignee):
        return True
    return task.project is not None and task.project.manager_id == current.id


def can_create_task_for(current: User, assigned_to: int | None) -> bool:
    if is_manager_or_admin(current):
        return True
    # Employee self-service creation (Phase 3): only ever assignable to themselves, or left
    # unassigned (which is a little unusual for self-service but not a privilege issue).
    return assigned_to is None or assigned_to == current.id


# ------------------------------------------------------------------------------ daily updates ----


def can_view_daily_update(current: User, update: DailyUpdate) -> bool:
    if is_admin(current) or update.user_id == current.id:
        return True
    return is_manager(current) and update.user is not None and same_team(current, update.user)


def can_modify_daily_update(current: User, update: DailyUpdate) -> bool:
    # Only the owner (or admin) ever writes a daily update — a manager can read a team
    # member's update but should never be able to edit someone else's self-report.
    return is_admin(current) or update.user_id == current.id


def can_create_daily_update_for(current: User, user_id: int) -> bool:
    return is_admin(current) or user_id == current.id


# ---------------------------------------------------------------------------------- projects ----


def can_view_project(current: User, has_task_in_project: bool = False) -> bool:
    if is_manager_or_admin(current):
        return True
    return has_task_in_project


def can_modify_project(current: User, project: Project) -> bool:
    if is_admin(current):
        return True
    return is_manager(current) and project.manager_id == current.id
