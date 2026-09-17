"""Duplicate detection for imported rows, at two levels:

- **Within the file itself**: two data rows that would create the same task (same project,
  assignee, title, and start date) — only the first is a candidate for insertion, later ones
  are flagged as duplicates of an earlier row.
- **Against the database**: a row that matches a task already in `tasks` (same project,
  assignee, title, and start date) is flagged as a duplicate of that existing task and skipped,
  rather than creating a second copy.

The matching key is deliberately narrow (not every field) — two rows for the same person on the
same project starting the same day, with the same title, are almost certainly the same task
re-entered, whereas differing estimated hours/status/etc. don't make them "different tasks" for
this purpose. See Known Limitations for the tradeoffs this implies.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.task import Task

DuplicateKey = tuple[int, int | None, str, Any]


def dedupe_key(task_kwargs: dict[str, Any]) -> DuplicateKey:
    return (
        task_kwargs["project_id"],
        task_kwargs.get("assigned_to"),
        task_kwargs["title"].strip().lower(),
        task_kwargs.get("start_date"),
    )


def find_existing_duplicate(db: Session, task_kwargs: dict[str, Any]) -> Task | None:
    stmt = select(Task).where(
        Task.project_id == task_kwargs["project_id"],
        func.lower(Task.title) == task_kwargs["title"].strip().lower(),
    )
    assigned_to = task_kwargs.get("assigned_to")
    stmt = stmt.where(Task.assigned_to == assigned_to) if assigned_to is not None else stmt.where(Task.assigned_to.is_(None))
    start_date = task_kwargs.get("start_date")
    stmt = stmt.where(Task.start_date == start_date) if start_date is not None else stmt.where(Task.start_date.is_(None))
    return db.scalars(stmt.limit(1)).first()
