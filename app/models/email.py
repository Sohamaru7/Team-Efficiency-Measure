from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import EmailDirection


class Email(Base):
    """One email associated with a task and/or a project (Phase 9). Never linked automatically
    from guessed content — `task_id`/`project_id` are always explicit, supplied by whoever (or
    whatever integration) ingests the email. `direction`/`is_external` are derived once at
    ingestion time from address domains only (metadata, not body content) — see
    `app.services.emailing.ingestion`. `body_text` is optional: metadata-only ingestion (no
    body) is fully supported, since most signal detection only needs addresses and timestamps.
    """

    __tablename__ = "emails"
    __table_args__ = (
        CheckConstraint("task_id IS NOT NULL OR project_id IS NOT NULL", name="ck_email_task_or_project"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_id: Mapped[str | None] = mapped_column(String(998), nullable=True, unique=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(998), nullable=True, index=True)
    subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    from_address: Mapped[str] = mapped_column(String(320), nullable=False)
    to_addresses: Mapped[str] = mapped_column(Text, nullable=False, doc="Comma-separated To addresses")
    cc_addresses: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Comma-separated Cc addresses")
    direction: Mapped[EmailDirection] = mapped_column(
        Enum(EmailDirection, name="email_direction"), nullable=False, index=True
    )
    is_external: Mapped[bool] = mapped_column(
        Boolean, nullable=False, index=True, doc="True if any party (From/To/Cc) is outside known internal domains"
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, doc="Who/what ingested this email, for audit"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self) -> str:
        return f"<Email id={self.id} subject={self.subject!r} task_id={self.task_id} project_id={self.project_id}>"
