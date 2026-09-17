"""Unit tests for app.services.daily_manager.change_tracking.diff_and_update_issue_state — the
significant-change / "don't repeatedly alert unless severity changes" mechanism. Builds
IssueFinding objects directly (no detection.py involved) to isolate the diffing logic itself.
"""

from datetime import date

from app.models.daily_manager import DailyManagerIssueState
from app.services.daily_manager.change_tracking import diff_and_update_issue_state
from app.services.daily_manager.snapshot import IssueFinding


def _finding(severity="medium", issue_type="overloaded_employee", target_key="employee:1"):
    return IssueFinding(issue_type, target_key, severity, f"{issue_type} label", {"x": 1})


def test_first_sighting_is_new(db_session):
    changes = diff_and_update_issue_state(db_session, [_finding()], date(2026, 8, 1))
    assert len(changes) == 1
    assert changes[0].change_type == "new"
    assert changes[0].severity == "medium"

    row = db_session.query(DailyManagerIssueState).one()
    assert row.last_reported_severity == "medium"
    assert row.resolved_at is None


def test_unchanged_severity_produces_no_change(db_session):
    diff_and_update_issue_state(db_session, [_finding(severity="medium")], date(2026, 8, 1))
    changes = diff_and_update_issue_state(db_session, [_finding(severity="medium")], date(2026, 8, 2))
    assert changes == []

    row = db_session.query(DailyManagerIssueState).one()
    assert row.last_seen_at == date(2026, 8, 2)  # still updated, just not reported
    assert row.last_reported_severity == "medium"


def test_escalation_is_reported(db_session):
    diff_and_update_issue_state(db_session, [_finding(severity="low")], date(2026, 8, 1))
    changes = diff_and_update_issue_state(db_session, [_finding(severity="high")], date(2026, 8, 2))
    assert len(changes) == 1
    assert changes[0].change_type == "escalated"
    assert changes[0].previous_severity == "low"
    assert changes[0].severity == "high"

    row = db_session.query(DailyManagerIssueState).one()
    assert row.last_reported_severity == "high"


def test_de_escalation_is_reported(db_session):
    diff_and_update_issue_state(db_session, [_finding(severity="high")], date(2026, 8, 1))
    changes = diff_and_update_issue_state(db_session, [_finding(severity="low")], date(2026, 8, 2))
    assert len(changes) == 1
    assert changes[0].change_type == "de-escalated"


def test_no_repeat_alert_across_three_unchanged_days(db_session):
    diff_and_update_issue_state(db_session, [_finding(severity="medium")], date(2026, 8, 1))
    d2 = diff_and_update_issue_state(db_session, [_finding(severity="medium")], date(2026, 8, 2))
    d3 = diff_and_update_issue_state(db_session, [_finding(severity="medium")], date(2026, 8, 3))
    assert d2 == []
    assert d3 == []


def test_resolved_when_no_longer_present(db_session):
    diff_and_update_issue_state(db_session, [_finding()], date(2026, 8, 1))
    changes = diff_and_update_issue_state(db_session, [], date(2026, 8, 2))
    assert len(changes) == 1
    assert changes[0].change_type == "resolved"

    row = db_session.query(DailyManagerIssueState).one()
    assert row.resolved_at == date(2026, 8, 2)


def test_resolved_issue_does_not_reappear_as_a_change_once_gone(db_session):
    diff_and_update_issue_state(db_session, [_finding()], date(2026, 8, 1))
    diff_and_update_issue_state(db_session, [], date(2026, 8, 2))
    changes_day3 = diff_and_update_issue_state(db_session, [], date(2026, 8, 3))
    assert changes_day3 == []  # already resolved -- staying absent is not a new change


def test_recurrence_after_resolution_is_new_again(db_session):
    diff_and_update_issue_state(db_session, [_finding(severity="medium")], date(2026, 8, 1))
    diff_and_update_issue_state(db_session, [], date(2026, 8, 2))
    changes = diff_and_update_issue_state(db_session, [_finding(severity="medium")], date(2026, 8, 3))
    assert len(changes) == 1
    assert changes[0].change_type == "new"

    row = db_session.query(DailyManagerIssueState).one()
    assert row.resolved_at is None
    assert row.first_detected_at == date(2026, 8, 3)


def test_multiple_independent_issues_tracked_separately(db_session):
    findings = [
        _finding(severity="low", issue_type="overloaded_employee", target_key="employee:1"),
        _finding(severity="high", issue_type="delayed_task", target_key="task:5"),
    ]
    changes = diff_and_update_issue_state(db_session, findings, date(2026, 8, 1))
    assert len(changes) == 2
    assert db_session.query(DailyManagerIssueState).count() == 2
