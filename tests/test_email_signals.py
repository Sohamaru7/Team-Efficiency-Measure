"""Unit tests for app.services.emailing.signals — pure functions over already-fetched Email
rows (no database access inside the functions themselves). Builds plain Email(...) objects
directly, same pattern as test_analytics_metrics.py for metrics.py's pure functions.
"""

from datetime import date, datetime, timezone

from app.models.email import Email
from app.models.enums import EmailDirection
from app.services.emailing.signals import (
    approval_delay,
    client_response_delay,
    external_blocker,
    pending_response,
    task_communication_summary,
)


def _email(direction, is_external, sent_at, subject=None, body=None, from_address="a@example.com", email_id=1):
    return Email(
        id=email_id, task_id=1, project_id=1, subject=subject, from_address=from_address,
        to_addresses="b@example.com", direction=direction, is_external=is_external,
        sent_at=sent_at, body_text=body,
    )


def _dt(day):
    return datetime(2026, 8, day, 9, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------------ client_response_delay ----


def test_client_response_delay_resolves_gap():
    outbound = _email(EmailDirection.OUTBOUND, True, _dt(1), email_id=1)
    inbound = _email(EmailDirection.INBOUND, True, _dt(3), email_id=2)
    result = client_response_delay([outbound, inbound])
    assert result is not None
    assert result.gap_days == 2
    assert result.outbound.email_id == 1
    assert result.inbound.email_id == 2


def test_client_response_delay_none_when_no_reply():
    outbound = _email(EmailDirection.OUTBOUND, True, _dt(1))
    assert client_response_delay([outbound]) is None


def test_client_response_delay_ignores_internal_only_emails():
    outbound = _email(EmailDirection.OUTBOUND, False, _dt(1))  # internal-only, not external
    inbound = _email(EmailDirection.INBOUND, False, _dt(3))
    assert client_response_delay([outbound, inbound]) is None


def test_client_response_delay_uses_latest_pair():
    e1 = _email(EmailDirection.OUTBOUND, True, _dt(1), email_id=1)
    e2 = _email(EmailDirection.INBOUND, True, _dt(2), email_id=2)
    e3 = _email(EmailDirection.OUTBOUND, True, _dt(5), email_id=3)
    e4 = _email(EmailDirection.INBOUND, True, _dt(10), email_id=4)
    result = client_response_delay([e1, e2, e3, e4])
    assert result.gap_days == 5
    assert result.outbound.email_id == 3
    assert result.inbound.email_id == 4


# ------------------------------------------------------------------------------ pending_response ----


def test_pending_response_when_last_email_is_unanswered_outbound():
    outbound = _email(EmailDirection.OUTBOUND, True, _dt(1))
    result = pending_response([outbound], as_of=date(2026, 8, 4))
    assert result is not None
    assert result.days_pending == 3


def test_pending_response_none_when_reply_received():
    outbound = _email(EmailDirection.OUTBOUND, True, _dt(1))
    inbound = _email(EmailDirection.INBOUND, True, _dt(2))
    assert pending_response([outbound, inbound], as_of=date(2026, 8, 5)) is None


def test_pending_response_none_for_internal_only_last_email():
    outbound = _email(EmailDirection.OUTBOUND, False, _dt(1))
    assert pending_response([outbound], as_of=date(2026, 8, 5)) is None


def test_pending_response_none_when_no_emails():
    assert pending_response([], as_of=date(2026, 8, 5)) is None


# -------------------------------------------------------------------------------- approval_delay ----


def test_approval_delay_resolved():
    request = _email(EmailDirection.OUTBOUND, True, _dt(1), subject="Need your approval", email_id=1)
    response = _email(EmailDirection.INBOUND, True, _dt(3), subject="Re: Need your approval", email_id=2)
    result = approval_delay([request, response], as_of=date(2026, 8, 10))
    assert result is not None
    assert result.gap_days == 2
    assert result.still_pending is False


def test_approval_delay_still_pending():
    request = _email(EmailDirection.OUTBOUND, True, _dt(1), subject="Please approve this")
    result = approval_delay([request], as_of=date(2026, 8, 5))
    assert result is not None
    assert result.still_pending is True
    assert result.gap_days is None


def test_approval_delay_body_checked_when_subject_silent():
    request = _email(EmailDirection.OUTBOUND, True, _dt(1), subject="Design homepage update", body="Can you approve the final draft?")
    result = approval_delay([request], as_of=date(2026, 8, 5))
    assert result is not None


def test_approval_delay_none_without_keyword():
    request = _email(EmailDirection.OUTBOUND, True, _dt(1), subject="Just checking in")
    assert approval_delay([request], as_of=date(2026, 8, 5)) is None


# ------------------------------------------------------------------------------ external_blocker ----


def test_external_blocker_detected_in_subject():
    email_row = _email(EmailDirection.INBOUND, True, _dt(1), subject="We are blocked on our end")
    result = external_blocker([email_row])
    assert result is not None
    assert "blocked" in result.matched_keywords


def test_external_blocker_detected_in_body_when_subject_silent():
    email_row = _email(EmailDirection.INBOUND, True, _dt(1), subject="Status update", body="We are currently on hold pending legal review.")
    result = external_blocker([email_row])
    assert result is not None
    assert "on hold" in result.matched_keywords


def test_external_blocker_ignores_internal_emails():
    email_row = _email(EmailDirection.INBOUND, False, _dt(1), subject="We are blocked")
    assert external_blocker([email_row]) is None


def test_external_blocker_none_without_keyword():
    email_row = _email(EmailDirection.INBOUND, True, _dt(1), subject="All good here")
    assert external_blocker([email_row]) is None


# ------------------------------------------------------------------- task_communication_summary ----


def test_task_communication_summary_counts():
    emails = [
        _email(EmailDirection.OUTBOUND, True, _dt(1)),
        _email(EmailDirection.INBOUND, True, _dt(2)),
        _email(EmailDirection.OUTBOUND, False, _dt(3)),
    ]
    summary = task_communication_summary(emails)
    assert summary.email_count == 3
    assert summary.external_count == 2
    assert summary.internal_count == 1
    assert summary.first_email_at == _dt(1)
    assert summary.last_email_at == _dt(3)


def test_task_communication_summary_empty():
    summary = task_communication_summary([])
    assert summary.email_count == 0
    assert summary.first_email_at is None
