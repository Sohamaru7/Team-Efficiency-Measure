from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_admin
from app.core.uploads import enforce_upload_size
from app.database.session import get_db
from app.models.user import User
from app.schemas.email import (
    DelayClassificationSchema,
    EmailDetailSchema,
    EmailIngestRequest,
    EmailSummarySchema,
    TaskSignalsSchema,
)
from app.services import project_service, task_service
from app.services.emailing import ingestion, queries
from app.services.emailing import signals as email_signals
from app.services.emailing.delay_classification import classify_delay
from app.services.emailing.ingestion import EmailIngestData
from app.services.emailing.permissions import can_view_email_content, can_view_task_or_project_emails

router = APIRouter(prefix="/api/emails", tags=["emails"])


def _validate_references(db: Session, task_id: int | None, project_id: int | None) -> int | None:
    """Validates task/project exist, and derives project_id from the task when the caller only
    gave a task_id (a real, deterministic lookup — never a guess).
    """
    if task_id is not None:
        task = task_service.get_task(db, task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        if project_id is None:
            project_id = task.project_id
    if project_id is not None and project_service.get_project(db, project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project_id


def _ingest(db: Session, data: EmailIngestData):
    try:
        return ingestion.ingest_email(db, data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An email with this message_id has already been ingested"
        ) from exc


@router.post("", response_model=EmailDetailSchema, status_code=status.HTTP_201_CREATED)
def ingest_email(
    data: EmailIngestRequest, db: Session = Depends(get_db), current_user: User = Depends(require_manager_or_admin)
) -> EmailDetailSchema:
    """Associate an email with a task and/or project. This is the primary integration point —
    a future live mailbox connector, or a script authenticating as a manager/admin, posts
    already-parsed fields here. `task_id`/`project_id` must reference real rows; neither is
    ever guessed from message content. `linked_by` is always the real authenticated caller,
    never a client-supplied id. Manager/admin only.
    """
    project_id = _validate_references(db, data.task_id, data.project_id)
    record = _ingest(
        db,
        EmailIngestData(
            task_id=data.task_id, project_id=project_id, subject=data.subject, from_address=data.from_address,
            to_addresses=list(data.to_addresses), cc_addresses=list(data.cc_addresses), sent_at=data.sent_at,
            body_text=data.body_text, message_id=data.message_id, in_reply_to=data.in_reply_to,
            linked_by=current_user.id,
        ),
    )
    return EmailDetailSchema.model_validate(record)


@router.post("/ingest-eml", response_model=EmailDetailSchema, status_code=status.HTTP_201_CREATED)
async def ingest_eml_file(
    file: UploadFile = File(...),
    task_id: int | None = Form(default=None),
    project_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_admin),
) -> EmailDetailSchema:
    """Same as `POST /api/emails`, but the email arrives as a raw `.eml` file (parsed with
    Python's `email` stdlib — no external service or credentials needed) instead of structured
    JSON. `task_id`/`project_id` are still supplied explicitly by the caller, never inferred
    from the file's content. Manager/admin only.
    """
    if task_id is None and project_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Either task_id or project_id must be provided")

    content = await file.read()
    enforce_upload_size(content)
    try:
        parsed = ingestion.parse_eml(content)
    except ingestion.InvalidEmailError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    resolved_project_id = _validate_references(db, task_id, project_id)
    record = _ingest(
        db,
        EmailIngestData(
            task_id=task_id, project_id=resolved_project_id, subject=parsed.subject, from_address=parsed.from_address,
            to_addresses=parsed.to_addresses, cc_addresses=parsed.cc_addresses, sent_at=parsed.sent_at,
            body_text=parsed.body_text, message_id=parsed.message_id, in_reply_to=parsed.in_reply_to,
            linked_by=current_user.id,
        ),
    )
    return EmailDetailSchema.model_validate(record)


@router.get("", response_model=list[EmailSummarySchema])
def list_emails(
    task_id: int | None = Query(default=None),
    project_id: int | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[EmailSummarySchema]:
    """Metadata-only list (no subject/addresses/body) — safe to show to any authenticated user
    regardless of the Phase 9 content-permission check, so a task page can show "N related
    emails" without leaking content. Call `GET /{id}` (which enforces that check) for the full
    email.
    """
    records = queries.list_emails(db, task_id=task_id, project_id=project_id, skip=skip, limit=limit)
    return [
        EmailSummarySchema(
            id=r.id, task_id=r.task_id, project_id=r.project_id, direction=r.direction,
            is_external=r.is_external, sent_at=r.sent_at, has_body=bool(r.body_text),
        )
        for r in records
    ]


def _require_task_access(db: Session, task_id: int, current_user: User):
    task = task_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if not can_view_task_or_project_emails(db, task_id=task_id, project_id=None, requesting_user_id=current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted to view this task's email signals")
    return task


@router.get("/tasks/{task_id}/signals", response_model=TaskSignalsSchema)
def get_task_signals(
    task_id: int,
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskSignalsSchema:
    """Deterministic, evidence-based signals detected from this task's linked emails: whether a
    response is pending, a resolved client-response gap, an approval request/response, and any
    external-blocker mentions. Every non-null field carries the exact email(s) it's based on.
    The permission check uses the real authenticated caller, never a client-supplied id.
    """
    _require_task_access(db, task_id, current_user)
    as_of = as_of or date.today()
    emails = queries.list_emails_for_task(db, task_id)

    return TaskSignalsSchema(
        task_id=task_id,
        communication=email_signals.task_communication_summary(emails),
        pending_response=email_signals.pending_response(emails, as_of),
        client_response_delay=email_signals.client_response_delay(emails),
        approval_delay=email_signals.approval_delay(emails, as_of),
        external_blocker=email_signals.external_blocker(emails),
    )


@router.get("/tasks/{task_id}/delay-classification", response_model=DelayClassificationSchema)
def get_task_delay_classification(
    task_id: int,
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DelayClassificationSchema:
    """The Phase 9 headline feature: reuses the existing, unmodified `detect_delays` formula for
    whether/how-long a task is delayed, and — only when real linked-email evidence supports one
    — adds a `delay_type`/`cause`/`duration_days` explanation. Never invents a cause when there
    is no supporting evidence; see `app.services.emailing.delay_classification`.
    """
    task = _require_task_access(db, task_id, current_user)
    result = classify_delay(db, task, as_of=as_of)
    return DelayClassificationSchema.model_validate(result)


@router.get("/{email_id}", response_model=EmailDetailSchema)
def get_email(
    email_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> EmailDetailSchema:
    record = queries.get_email(db, email_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    if not can_view_email_content(db, record, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted to view this email's content")
    return EmailDetailSchema.model_validate(record)
