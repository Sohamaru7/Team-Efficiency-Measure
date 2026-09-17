"""Deterministic, evidence-based signal detection over a task's linked emails. Every function
here is pure (takes an already-fetched `list[Email]`, never queries the database itself) and
returns either `None` (no signal found — never guessed) or a small dataclass carrying the exact
email(s) it's based on, so every signal is auditable back to real rows.

"Metadata and content only when necessary" (Phase 9 brief): `client_response_delay` and
`pending_response` use only `direction`/`is_external`/`sent_at` — pure metadata, no message
content read at all. `approval_delay` and `external_blocker` need keyword matching, and even
there the subject (also metadata) is checked first; the body is only consulted if the subject
alone doesn't already answer the question.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.models.email import Email
from app.models.enums import EmailDirection
from app.services.emailing.constants import APPROVAL_KEYWORDS, BLOCKER_KEYWORDS


@dataclass
class EmailEvidence:
    email_id: int
    subject: str | None
    from_address: str
    sent_at: datetime


def _evidence(email_row: Email) -> EmailEvidence:
    return EmailEvidence(email_id=email_row.id, subject=email_row.subject, from_address=email_row.from_address, sent_at=email_row.sent_at)


@dataclass
class ClientResponseDelaySignal:
    outbound: EmailEvidence
    inbound: EmailEvidence
    gap_days: int


@dataclass
class PendingResponseSignal:
    last_outbound: EmailEvidence
    days_pending: int


@dataclass
class ApprovalDelaySignal:
    request: EmailEvidence
    response: EmailEvidence | None
    gap_days: int | None
    still_pending: bool


@dataclass
class ExternalBlockerSignal:
    evidence: list[EmailEvidence]
    matched_keywords: list[str]


@dataclass
class TaskCommunicationSummary:
    email_count: int
    external_count: int
    internal_count: int
    first_email_at: datetime | None
    last_email_at: datetime | None


def _day_gap(later: datetime, earlier: datetime) -> int:
    return (later.date() - earlier.date()).days


def client_response_delay(emails: list[Email]) -> ClientResponseDelaySignal | None:
    """The most recent resolved request/reply pair: an outbound email to an external party,
    followed by an inbound reply. Pure metadata (direction + is_external + sent_at) — no
    content read. Returns the *latest* such pair if there are several, since that's the one
    most relevant to a task's current state.
    """
    ordered = sorted(emails, key=lambda e: e.sent_at)
    result: ClientResponseDelaySignal | None = None
    pending_outbound: Email | None = None
    for email_row in ordered:
        if email_row.direction == EmailDirection.OUTBOUND and email_row.is_external:
            pending_outbound = email_row
        elif email_row.direction == EmailDirection.INBOUND and pending_outbound is not None:
            result = ClientResponseDelaySignal(
                outbound=_evidence(pending_outbound), inbound=_evidence(email_row), gap_days=_day_gap(email_row.sent_at, pending_outbound.sent_at)
            )
            pending_outbound = None
    return result


def pending_response(emails: list[Email], as_of: date) -> PendingResponseSignal | None:
    """True if the most recent linked email is an outbound message to an external party with
    no reply yet as of `as_of`. Pure metadata.
    """
    ordered = sorted(emails, key=lambda e: e.sent_at)
    if not ordered:
        return None
    last = ordered[-1]
    if last.direction != EmailDirection.OUTBOUND or not last.is_external:
        return None
    days = (as_of - last.sent_at.date()).days
    if days < 0:
        return None
    return PendingResponseSignal(last_outbound=_evidence(last), days_pending=days)


def _find_keywords(email_row: Email, keywords: tuple[str, ...]) -> list[str]:
    subject = (email_row.subject or "").lower()
    found = [kw for kw in keywords if kw in subject]
    if found:
        return found
    body = (email_row.body_text or "").lower()
    if not body:
        return []
    return [kw for kw in keywords if kw in body]


def approval_delay(emails: list[Email], as_of: date) -> ApprovalDelaySignal | None:
    """An approval was requested (subject/body matches APPROVAL_KEYWORDS, subject checked
    first) in an outbound email; either it was answered (inbound reply after it -> gap_days)
    or it's still pending as of `as_of`.
    """
    relevant = [e for e in emails if _find_keywords(e, APPROVAL_KEYWORDS)]
    if not relevant:
        return None
    ordered = sorted(relevant, key=lambda e: e.sent_at)
    request = next((e for e in ordered if e.direction == EmailDirection.OUTBOUND), None)
    if request is None:
        return None
    response = next((e for e in ordered if e.sent_at > request.sent_at and e.direction == EmailDirection.INBOUND), None)
    if response is not None:
        return ApprovalDelaySignal(
            request=_evidence(request), response=_evidence(response), gap_days=_day_gap(response.sent_at, request.sent_at), still_pending=False
        )
    days = (as_of - request.sent_at.date()).days
    if days < 0:
        return None
    return ApprovalDelaySignal(request=_evidence(request), response=None, gap_days=None, still_pending=True)


def external_blocker(emails: list[Email]) -> ExternalBlockerSignal | None:
    """External emails whose subject/body mentions a blocker keyword (subject checked first)."""
    matches: list[EmailEvidence] = []
    matched_keywords: set[str] = set()
    for email_row in emails:
        if not email_row.is_external:
            continue
        found = _find_keywords(email_row, BLOCKER_KEYWORDS)
        if found:
            matches.append(_evidence(email_row))
            matched_keywords.update(found)
    if not matches:
        return None
    return ExternalBlockerSignal(evidence=matches, matched_keywords=sorted(matched_keywords))


def task_communication_summary(emails: list[Email]) -> TaskCommunicationSummary:
    """Base signal: that communication happened at all. Deliberately has no notion of
    "productivity" — this is evidence of correspondence, not a quality or output measure (see
    Known Limitations: email activity is never fed into any efficiency/quality score).
    """
    if not emails:
        return TaskCommunicationSummary(email_count=0, external_count=0, internal_count=0, first_email_at=None, last_email_at=None)
    ordered = sorted(emails, key=lambda e: e.sent_at)
    external = sum(1 for e in emails if e.is_external)
    return TaskCommunicationSummary(
        email_count=len(emails),
        external_count=external,
        internal_count=len(emails) - external,
        first_email_at=ordered[0].sent_at,
        last_email_at=ordered[-1].sent_at,
    )
