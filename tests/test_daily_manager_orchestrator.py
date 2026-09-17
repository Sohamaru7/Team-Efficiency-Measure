"""DB-integration tests for app.services.daily_manager.orchestrator.run_daily_manager — the
full 11-step pipeline. Covers idempotency ("runs once per working day"), the weekend skip, the
report's persisted content, and that a second run on an unchanged day doesn't re-alert/re-act.
"""

from datetime import date, timedelta

from app.models.agent_action import AgentAction
from app.models.daily_manager import DailyManagerReport
from app.models.enums import ProjectStatus, TaskPriority, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.daily_manager.orchestrator import is_working_day, run_daily_manager


def _seed(db_session):
    manager = User(name="Manager Orch", email="mgr-orch@example.com", role=UserRole.MANAGER, department="Engineering")
    alice = User(name="Alice Orch", email="alice-orch@example.com", department="Engineering")
    bob = User(name="Bob Orch", email="bob-orch@example.com", department="Engineering")
    db_session.add_all([manager, alice, bob])
    db_session.commit()
    project = Project(name="Orch Project", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add(project)
    db_session.commit()
    return {"manager": manager, "alice": alice, "bob": bob, "project": project}


def test_is_working_day():
    assert is_working_day(date(2026, 8, 17)) is True  # Monday
    assert is_working_day(date(2026, 8, 21)) is True  # Friday
    assert is_working_day(date(2026, 8, 22)) is False  # Saturday
    assert is_working_day(date(2026, 8, 23)) is False  # Sunday


def test_run_skips_on_weekend(db_session):
    outcome = run_daily_manager(db_session, as_of=date(2026, 8, 22))  # Saturday
    assert outcome.status == "skipped_non_working_day"
    assert outcome.report is None
    assert db_session.query(DailyManagerReport).count() == 0


def test_run_force_bypasses_weekend_skip(db_session):
    _seed(db_session)
    outcome = run_daily_manager(db_session, as_of=date(2026, 8, 22), force=True)
    assert outcome.status == "ran"
    assert outcome.report is not None


def test_run_on_normal_day_creates_report(db_session):
    _seed(db_session)
    monday = date(2026, 8, 17)
    outcome = run_daily_manager(db_session, as_of=monday)
    assert outcome.status == "ran"
    assert outcome.report.run_date == monday
    assert db_session.query(DailyManagerReport).count() == 1


def test_second_run_same_day_is_idempotent(db_session):
    _seed(db_session)
    monday = date(2026, 8, 17)
    first = run_daily_manager(db_session, as_of=monday)
    second = run_daily_manager(db_session, as_of=monday)

    assert second.status == "already_ran"
    assert second.report.id == first.report.id
    assert db_session.query(DailyManagerReport).count() == 1


def test_second_run_same_day_does_not_double_act(db_session):
    seed = _seed(db_session)
    monday = date(2026, 8, 17)
    for i in range(5):
        db_session.add(Task(
            project_id=seed["project"].id, assigned_to=seed["alice"].id, title=f"Overload {i}",
            status=TaskStatus.IN_PROGRESS, priority=TaskPriority.HIGH, estimated_hours=20,
        ))
    db_session.commit()

    run_daily_manager(db_session, as_of=monday)
    action_count_after_first = db_session.query(AgentAction).count()
    run_daily_manager(db_session, as_of=monday)
    action_count_after_second = db_session.query(AgentAction).count()

    assert action_count_after_first > 0
    assert action_count_after_second == action_count_after_first  # no duplicate notification


def test_next_day_unchanged_severity_does_not_re_alert(db_session):
    seed = _seed(db_session)
    for i in range(5):
        db_session.add(Task(
            project_id=seed["project"].id, assigned_to=seed["alice"].id, title=f"Overload {i}",
            status=TaskStatus.IN_PROGRESS, priority=TaskPriority.HIGH, estimated_hours=20,
        ))
    db_session.commit()

    monday = date(2026, 8, 17)
    tuesday = date(2026, 8, 18)
    run_daily_manager(db_session, as_of=monday)
    action_count_after_monday = db_session.query(AgentAction).count()

    run_daily_manager(db_session, as_of=tuesday)
    action_count_after_tuesday = db_session.query(AgentAction).count()

    assert action_count_after_tuesday == action_count_after_monday  # same overload, same severity -> silent

    import json

    tuesday_report = db_session.query(DailyManagerReport).filter_by(run_date=tuesday).one()
    tuesday_data = json.loads(tuesday_report.summary_json)
    assert tuesday_data["major_changes"] == []
    assert tuesday_report.action_required is False


def test_report_contains_all_required_sections(db_session):
    seed = _seed(db_session)
    monday = date(2026, 8, 17)
    db_session.add(Task(
        project_id=seed["project"].id, assigned_to=seed["alice"].id, title="Completed today",
        status=TaskStatus.COMPLETED, completed_date=monday, quality_score=90,
    ))
    db_session.commit()

    outcome = run_daily_manager(db_session, as_of=monday)

    import json

    data = json.loads(outcome.report.summary_json)
    for key in (
        "team_efficiency", "major_changes", "completed_work", "delayed_work", "at_risk_deadlines",
        "workload_problems", "quality_issues", "project_risks", "recommended_actions", "actions_taken",
    ):
        assert key in data

    assert len(data["completed_work"]) == 1
    assert data["completed_work"][0]["title"] == "Completed today"


def test_full_scenario_overload_and_at_risk_deadline_produces_action_and_recommendation(db_session):
    seed = _seed(db_session)
    monday = date(2026, 8, 17)
    for i in range(5):
        db_session.add(Task(
            project_id=seed["project"].id, assigned_to=seed["alice"].id, title=f"Overload {i}",
            status=TaskStatus.IN_PROGRESS, priority=TaskPriority.HIGH, estimated_hours=20,
            deadline=monday + timedelta(days=1),
        ))
    db_session.commit()

    outcome = run_daily_manager(db_session, as_of=monday)
    assert outcome.report.action_required is True
    assert outcome.report.actions_taken_count >= 1

    import json

    data = json.loads(outcome.report.summary_json)
    assert any(c["issue_type"] == "overloaded_employee" for c in data["major_changes"])
    assert len(data["recommended_actions"]) >= 1
    assert any(a["action"] == "send_notification" for a in data["actions_taken"])
