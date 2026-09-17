"""Enriches a task's delay with email evidence — WITHOUT touching `metrics.detect_delays`
itself. `detect_delays` (Phase 4, unmodified) remains the single source of truth for *whether*
a task is delayed and by how many days against its deadline; this module only adds an
optional, additive explanation of *why*, and only when real linked-email evidence supports one.
Per the Phase 9 brief: "do not modify existing analytics formulas unless the email-derived data
is explicitly available and validated" — so when there is no linked email, or the linked emails
don't resolve to a clear signal, this returns an honest "unclassified" result rather than a
guess, and the existing `TaskDelay.delay_days` from the untouched formula is still reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models.task import Task
from app.services.analytics.metrics import detect_delays
from app.services.emailing import signals as email_signals
from app.services.emailing.constants import EXTERNAL_HINT_KEYWORDS
from app.services.emailing.queries import list_emails_for_task


@dataclass
class DelayClassificationResult:
    task_id: int
    is_delayed: bool
    delay_type: str | None  # "external" | None (no "internal" signal source exists yet — see README)
    cause: str | None
    duration_days: int | None
    confidence: str  # "high" | "medium" | "low" | "none" | "n/a"
    note: str
    evidence_email_ids: list[int] = field(default_factory=list)


def classify_delay(db: Session, task: Task, as_of: date | None = None) -> DelayClassificationResult:
    as_of = as_of or date.today()

    # The existing, unmodified pure formula — called with a one-task list so its behavior is
    # identical to how it's used everywhere else (see app.services.analytics.metrics).
    delay = detect_delays([task], as_of=as_of)[0]

    if not delay.is_delayed:
        return DelayClassificationResult(
            task_id=task.id, is_delayed=False, delay_type=None, cause=None, duration_days=None,
            confidence="n/a", note="Task is not delayed.",
        )

    emails = list_emails_for_task(db, task.id)
    if not emails:
        return DelayClassificationResult(
            task_id=task.id, is_delayed=True, delay_type=None, cause=None, duration_days=delay.delay_days,
            confidence="none", note="Task is delayed but no linked emails exist to classify the cause.",
        )

    delay_reason_lower = (task.delay_reason or "").lower()
    external_hint = any(kw in delay_reason_lower for kw in EXTERNAL_HINT_KEYWORDS)

    # Approval delay is checked before the generic client-response-delay signal because it's
    # keyword-confirmed (more specific) — an outbound/inbound pair that's explicitly about an
    # approval should be labeled "Approval delay", not the more generic "Client response delay".
    approval = email_signals.approval_delay(emails, as_of)
    if approval is not None and not approval.still_pending:
        return DelayClassificationResult(
            task_id=task.id, is_delayed=True, delay_type="external", cause="Approval delay",
            duration_days=approval.gap_days, confidence="medium",
            note=f"Approval response took {approval.gap_days} day(s).",
            evidence_email_ids=[approval.request.email_id, approval.response.email_id],
        )

    client_delay = email_signals.client_response_delay(emails)
    if client_delay is not None:
        return DelayClassificationResult(
            task_id=task.id, is_delayed=True, delay_type="external", cause="Client response delay",
            duration_days=client_delay.gap_days, confidence="high" if external_hint else "medium",
            note=f"Client replied {client_delay.gap_days} day(s) after the last outbound email.",
            evidence_email_ids=[client_delay.outbound.email_id, client_delay.inbound.email_id],
        )

    if approval is not None and approval.still_pending:
        return DelayClassificationResult(
            task_id=task.id, is_delayed=True, delay_type="external", cause="Approval pending",
            duration_days=None, confidence="medium",
            note="Still awaiting an approval response as of the reference date.",
            evidence_email_ids=[approval.request.email_id],
        )

    pending = email_signals.pending_response(emails, as_of)
    if pending is not None:
        return DelayClassificationResult(
            task_id=task.id, is_delayed=True, delay_type="external", cause="Awaiting external response",
            duration_days=pending.days_pending, confidence="medium",
            note="The most recent linked email is an outbound message to an external party with no reply yet.",
            evidence_email_ids=[pending.last_outbound.email_id],
        )

    blocker = email_signals.external_blocker(emails)
    if blocker is not None:
        return DelayClassificationResult(
            task_id=task.id, is_delayed=True, delay_type="external", cause="External blocker mentioned",
            duration_days=None, confidence="low",
            note=f"Linked external email(s) mention: {', '.join(blocker.matched_keywords)}.",
            evidence_email_ids=[e.email_id for e in blocker.evidence],
        )

    return DelayClassificationResult(
        task_id=task.id, is_delayed=True, delay_type=None, cause=None, duration_days=delay.delay_days,
        confidence="none", note="Task is delayed and has linked emails, but no clear external-delay signal was found.",
    )
