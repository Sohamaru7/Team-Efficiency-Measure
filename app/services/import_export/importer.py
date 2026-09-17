"""The import pipeline: Observe the upload -> parse -> map columns -> validate each row ->
check for duplicates -> (if not a dry run) insert. One function, `run_import`, drives both the
preview and commit endpoints — preview always passes `dry_run=True` (parses, validates, and
reports what *would* happen, writes nothing) and commit passes `dry_run=False` (does everything
preview does, plus actually creates a `Task` per accepted row and logs one `ImportHistory` row
for the whole run). Running the identical pipeline for both means a preview can never lie about
what a commit will do.

Every accepted row is inserted through `TaskCreate` + `task_service.create_task` — the exact
same schema and service function `POST /api/tasks` uses — never a raw ORM write, so import can
never bypass the validation the rest of the app already trusts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.import_history import ImportHistory
from app.models.project import Project
from app.models.user import User
from app.schemas.task import TaskCreate
from app.services import task_service
from app.services.import_export.column_mapping import map_columns
from app.services.import_export.constants import MAX_ERROR_LOG_CHARS
from app.services.import_export.duplicates import dedupe_key, find_existing_duplicate
from app.services.import_export.errors import ImportFileError, MissingRequiredColumnsError
from app.services.import_export.parsing import parse_upload
from app.services.import_export.validation import validate_row


@dataclass
class RowOutcome:
    row_number: int  # 1-based, counting data rows only (the header row is not row 1)
    status: str  # "accepted" | "rejected" | "duplicate"
    employee: str | None
    task: str | None
    project: str | None
    errors: list[str] = field(default_factory=list)
    task_id: int | None = None


@dataclass
class ImportResult:
    filename: str
    dry_run: bool
    column_mapping: dict[str, str | None]
    rows_processed: int
    rows_accepted: int
    rows_rejected: int
    rows_duplicate: int
    rows: list[RowOutcome] = field(default_factory=list)
    file_error: str | None = None
    history_id: int | None = None


def run_import(db: Session, *, filename: str, content: bytes, dry_run: bool, imported_by: int | None) -> ImportResult:
    try:
        parsed = parse_upload(filename, content)
        mapping = map_columns(parsed.headers)
        if mapping.missing_required:
            raise MissingRequiredColumnsError(mapping.missing_required)
    except ImportFileError as exc:
        result = ImportResult(
            filename=filename,
            dry_run=dry_run,
            column_mapping={},
            rows_processed=0,
            rows_accepted=0,
            rows_rejected=0,
            rows_duplicate=0,
            file_error=str(exc),
        )
        if not dry_run:
            result.history_id = _log_history(db, filename, imported_by, result, file_error=str(exc))
        return result

    projects_by_name = {p.name.strip().lower(): p for p in db.scalars(select(Project))}
    users_by_name = {u.name.strip().lower(): u for u in db.scalars(select(User))}

    outcomes: list[RowOutcome] = []
    seen_keys: set[tuple] = set()
    accepted = rejected = duplicate = 0

    for i, raw_row in enumerate(parsed.rows, start=1):
        mapped = {canonical: (raw_row.get(header) if header else None) for canonical, header in mapping.mapping.items()}
        validation = validate_row(mapped, projects_by_name, users_by_name)

        if validation.errors:
            rejected += 1
            outcomes.append(
                RowOutcome(
                    row_number=i,
                    status="rejected",
                    employee=validation.employee_display,
                    task=validation.task_display,
                    project=validation.project_display,
                    errors=validation.errors,
                )
            )
            continue

        task_kwargs = validation.task_kwargs
        assert task_kwargs is not None

        key = dedupe_key(task_kwargs)
        if key in seen_keys:
            duplicate += 1
            outcomes.append(
                RowOutcome(
                    row_number=i,
                    status="duplicate",
                    employee=validation.employee_display,
                    task=validation.task_display,
                    project=validation.project_display,
                    errors=["Duplicate of an earlier row in this file"],
                )
            )
            continue

        existing = find_existing_duplicate(db, task_kwargs)
        if existing is not None:
            duplicate += 1
            outcomes.append(
                RowOutcome(
                    row_number=i,
                    status="duplicate",
                    employee=validation.employee_display,
                    task=validation.task_display,
                    project=validation.project_display,
                    errors=[f"Matches existing task #{existing.id}"],
                )
            )
            continue

        seen_keys.add(key)

        if dry_run:
            accepted += 1
            outcomes.append(
                RowOutcome(
                    row_number=i,
                    status="accepted",
                    employee=validation.employee_display,
                    task=validation.task_display,
                    project=validation.project_display,
                )
            )
            continue

        try:
            task = task_service.create_task(db, TaskCreate(**task_kwargs))
        except (ValidationError, IntegrityError) as exc:
            db.rollback()
            rejected += 1
            outcomes.append(
                RowOutcome(
                    row_number=i,
                    status="rejected",
                    employee=validation.employee_display,
                    task=validation.task_display,
                    project=validation.project_display,
                    errors=[f"Backend validation failed: {exc}"],
                )
            )
            continue

        accepted += 1
        outcomes.append(
            RowOutcome(
                row_number=i,
                status="accepted",
                employee=validation.employee_display,
                task=validation.task_display,
                project=validation.project_display,
                task_id=task.id,
            )
        )

    result = ImportResult(
        filename=filename,
        dry_run=dry_run,
        column_mapping=mapping.mapping,
        rows_processed=len(parsed.rows),
        rows_accepted=accepted,
        rows_rejected=rejected + duplicate,
        rows_duplicate=duplicate,
        rows=outcomes,
    )

    if not dry_run:
        result.history_id = _log_history(db, filename, imported_by, result, file_error=None)

    return result


def _log_history(
    db: Session, filename: str, imported_by: int | None, result: ImportResult, *, file_error: str | None
) -> int:
    if file_error is not None:
        error_payload: Any = [{"file_error": file_error}]
    else:
        error_payload = [
            {"row": o.row_number, "status": o.status, "errors": o.errors} for o in result.rows if o.status != "accepted"
        ]
    errors_json = json.dumps(error_payload, default=str)
    if len(errors_json) > MAX_ERROR_LOG_CHARS:
        errors_json = errors_json[:MAX_ERROR_LOG_CHARS]

    history = ImportHistory(
        filename=filename,
        imported_by=imported_by,
        rows_processed=result.rows_processed,
        rows_accepted=result.rows_accepted,
        rows_rejected=result.rows_rejected,
        errors=errors_json,
    )
    db.add(history)
    db.commit()
    db.refresh(history)
    return history.id
