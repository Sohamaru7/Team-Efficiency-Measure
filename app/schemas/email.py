from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.enums import EmailDirection


class EmailIngestRequest(BaseModel):
    task_id: Optional[int] = None
    project_id: Optional[int] = None
    subject: Optional[str] = Field(default=None, max_length=998)
    from_address: EmailStr
    to_addresses: list[EmailStr] = Field(min_length=1)
    cc_addresses: list[EmailStr] = Field(default_factory=list)
    sent_at: datetime
    body_text: Optional[str] = None
    message_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    linked_by: Optional[int] = None

    @model_validator(mode="after")
    def require_task_or_project(self) -> "EmailIngestRequest":
        if self.task_id is None and self.project_id is None:
            raise ValueError("Either task_id or project_id must be provided")
        return self


class EmailSummarySchema(BaseModel):
    """Redacted view: no subject, addresses, or body — safe to show to anyone regardless of
    the Phase 9 permission check, so a task page can show "N related emails" without leaking
    content to a viewer who isn't the assignee/manager/admin.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: Optional[int] = None
    project_id: Optional[int] = None
    direction: EmailDirection
    is_external: bool
    sent_at: datetime
    has_body: bool = False


class EmailDetailSchema(BaseModel):
    """Full view — only ever returned after `permissions.can_view_email_content` passes."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: Optional[int] = None
    project_id: Optional[int] = None
    subject: Optional[str] = None
    from_address: str
    to_addresses: str
    cc_addresses: Optional[str] = None
    direction: EmailDirection
    is_external: bool
    sent_at: datetime
    body_text: Optional[str] = None
    message_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    linked_by: Optional[int] = None
    created_at: datetime


class EmailEvidenceSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email_id: int
    subject: Optional[str] = None
    from_address: str
    sent_at: datetime


class PendingResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    last_outbound: EmailEvidenceSchema
    days_pending: int


class ClientResponseDelaySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    outbound: EmailEvidenceSchema
    inbound: EmailEvidenceSchema
    gap_days: int


class ApprovalDelaySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request: EmailEvidenceSchema
    response: Optional[EmailEvidenceSchema] = None
    gap_days: Optional[int] = None
    still_pending: bool


class ExternalBlockerSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evidence: list[EmailEvidenceSchema]
    matched_keywords: list[str]


class CommunicationSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email_count: int
    external_count: int
    internal_count: int
    first_email_at: Optional[datetime] = None
    last_email_at: Optional[datetime] = None


class TaskSignalsSchema(BaseModel):
    task_id: int
    communication: CommunicationSummarySchema
    pending_response: Optional[PendingResponseSchema] = None
    client_response_delay: Optional[ClientResponseDelaySchema] = None
    approval_delay: Optional[ApprovalDelaySchema] = None
    external_blocker: Optional[ExternalBlockerSchema] = None


class DelayClassificationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    is_delayed: bool
    delay_type: Optional[str] = None
    cause: Optional[str] = None
    duration_days: Optional[int] = None
    confidence: str
    note: str
    evidence_email_ids: list[int] = []
