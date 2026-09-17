from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class DailyManagerReport(Base):
    """One row per autonomous daily-manager run (Phase 10) — the audit record that a run
    happened on this date, plus the full generated report. `run_date` is unique: the pipeline
    enforces "once per working day" by checking for an existing row before doing any work (see
    `app.services.daily_manager.orchestrator.run_daily_manager`), so this table is also what
    makes re-invoking the same day's run idempotent rather than double-alerting/double-acting.

    `summary_json` holds the full structured report (major changes, completed/delayed work,
    at-risk deadlines, workload/quality/project issues, recommended actions, actions taken) as
    JSON text — the same "structured JSON in a Text column" pattern already used for
    `AgentAction.payload`/`.result` and `ImportHistory.errors`, rather than a dozen new
    normalized tables for each report section.
    """

    __tablename__ = "daily_manager_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date_type] = mapped_column(Date, nullable=False, unique=True, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    team_efficiency: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    action_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    actions_taken_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<DailyManagerReport id={self.id} run_date={self.run_date} action_required={self.action_required}>"


class DailyManagerIssueState(Base):
    """Tracks one ongoing issue (`issue_type` + `target_key`, e.g. `"overloaded_employee"` +
    `"employee:12"`) across daily runs, so the pipeline can tell "brand new," "got worse,"
    "got better," "resolved," or "same as yesterday" apart — and only the first four are ever
    reported as a "significant change" (see `app.services.daily_manager.change_tracking`).
    `last_reported_severity` only changes when a change is actually reported, which is exactly
    what implements "don't repeatedly alert about the same issue unless its severity changes":
    an issue sitting at the same severity for a week updates `last_seen_at` every run but never
    produces another alert.
    """

    __tablename__ = "daily_manager_issue_state"
    __table_args__ = (UniqueConstraint("issue_type", "target_key", name="uq_daily_manager_issue_state_type_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    first_detected_at: Mapped[date_type] = mapped_column(Date, nullable=False)
    last_seen_at: Mapped[date_type] = mapped_column(Date, nullable=False)
    last_reported_severity: Mapped[str] = mapped_column(String(20), nullable=False)
    resolved_at: Mapped[date_type | None] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return f"<DailyManagerIssueState issue_type={self.issue_type!r} target_key={self.target_key!r} severity={self.severity!r}>"
