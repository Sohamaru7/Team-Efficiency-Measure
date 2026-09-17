from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import AgentActionStatus


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    # Kept for backward compatibility with Phase 6 (which only ever wrote True). Still set
    # consistently (True for AUTO_APPROVED/APPROVED, False otherwise) but `status` below is the
    # authoritative field going forward — it distinguishes "auto-approved" from "awaiting
    # approval" from "rejected", which a plain boolean can't.
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    # Phase 7 additions — additive-only migration (see migrations/versions/), no existing
    # column was changed or dropped.
    status: Mapped[AgentActionStatus] = mapped_column(
        Enum(AgentActionStatus, name="agent_action_status"),
        nullable=False,
        default=AgentActionStatus.PENDING,
        server_default=AgentActionStatus.PENDING.value,
        index=True,
    )
    result: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Outcome of the action once executed (success summary or error message)."
    )
    payload: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="JSON-encoded proposed parameters for a PENDING write action, used to execute it "
        "later if a manager approves it. Always going through the same Pydantic schemas and "
        "service functions the CRUD API uses — never applied directly to the ORM.",
    )

    def __repr__(self) -> str:
        return f"<AgentAction id={self.id} agent_type={self.agent_type!r} action={self.action!r} status={self.status.value}>"
