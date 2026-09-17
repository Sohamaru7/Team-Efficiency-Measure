"""Privacy control for email content (Phase 9): who may see one email's subject/addresses/body,
or a task's derived email signals (which are themselves partly content-derived — e.g. keyword
matches — so they're gated the same way).

This app has no real authentication anywhere (see README Known Limitations) — a caller supplies
`requesting_user_id` the same way `changed_by`/`imported_by` are supplied elsewhere, and it is
trusted at face value rather than cryptographically verified. Within that existing trust model,
this function is a real, deterministic, server-enforced rule (not a rubber stamp): the intended
access model is "task assignee, the linked project's manager, or any manager/admin" — everyone
else gets metadata-only visibility via `EmailSummarySchema` and a 403 everywhere else.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.email import Email
from app.models.enums import UserRole
from app.services import project_service, task_service, user_service


def can_view_task_or_project_emails(
    db: Session, *, task_id: int | None, project_id: int | None, requesting_user_id: int | None
) -> bool:
    if requesting_user_id is None:
        return False

    user = user_service.get_user(db, requesting_user_id)
    if user is None:
        return False

    if user.role in (UserRole.MANAGER, UserRole.ADMIN):
        return True

    task = task_service.get_task(db, task_id) if task_id is not None else None
    if task is not None and task.assigned_to == requesting_user_id:
        return True

    resolved_project_id = project_id if project_id is not None else (task.project_id if task else None)
    if resolved_project_id is not None:
        project = project_service.get_project(db, resolved_project_id)
        if project is not None and project.manager_id == requesting_user_id:
            return True

    return False


def can_view_email_content(db: Session, email_row: Email, requesting_user_id: int | None) -> bool:
    return can_view_task_or_project_emails(
        db, task_id=email_row.task_id, project_id=email_row.project_id, requesting_user_id=requesting_user_id
    )
