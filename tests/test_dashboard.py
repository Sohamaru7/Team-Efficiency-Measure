"""Integration tests for app.services.analytics.dashboard against a realistic seeded SQLite
dataset. Numbers that are unambiguous consequences of the filtering rules (task counts, workload
hours, delayed/upcoming lists) are hand-computed and asserted precisely; `overall_team_efficiency`
is instead cross-checked against directly calling `calculate_employee_score` for each resolved
member (mirroring how `calculate_team_score` itself is already tested), since Phase 4's scoring
formulas are covered by their own test suite.
"""

from datetime import date

import pytest

from app.models.enums import ProjectStatus, TaskStatus, UserRole
from app.models.daily_update import DailyUpdate
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.analytics.dashboard import calculate_efficiency_trend, get_manager_dashboard
from app.services.analytics.scoring import calculate_employee_score

AS_OF = date(2026, 8, 14)


def _seed(db_session):
    manager = User(name="Priya Shah", email="priya-dash@example.com", role=UserRole.MANAGER, department="Management")
    alice = User(name="Alice", email="alice-dash@example.com", department="Engineering")
    bob = User(name="Bob", email="bob-dash@example.com", department="Engineering")
    carol = User(name="Carol", email="carol-dash@example.com", department="Sales")
    db_session.add_all([manager, alice, bob, carol])
    db_session.commit()

    p1 = Project(name="Platform", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    p2 = Project(name="Storefront", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add_all([p1, p2])
    db_session.commit()

    tasks = {
        "t1": Task(  # alice, P1, completed on time, 4-day duration
            project_id=p1.id, assigned_to=alice.id, title="Design schema",
            status=TaskStatus.COMPLETED, estimated_hours=5,
            start_date=date(2026, 8, 1), completed_date=date(2026, 8, 5), deadline=date(2026, 8, 10),
        ),
        "t2": Task(  # bob, P1, overdue (not started, deadline in the past)
            project_id=p1.id, assigned_to=bob.id, title="Provision servers",
            status=TaskStatus.NOT_STARTED, estimated_hours=3, deadline=date(2026, 8, 10),
            delay_reason="waiting on procurement",
        ),
        "t3": Task(  # alice, P1, in progress, 2 days left -> HIGH risk
            project_id=p1.id, assigned_to=alice.id, title="Write migration",
            status=TaskStatus.IN_PROGRESS, estimated_hours=2, deadline=date(2026, 8, 16),
        ),
        "t4": Task(  # bob, P1, in progress, far deadline -> LOW risk
            project_id=p1.id, assigned_to=bob.id, title="Load testing",
            status=TaskStatus.IN_PROGRESS, estimated_hours=4, deadline=date(2026, 8, 25),
        ),
        "t5": Task(  # carol, P2, completed on time, 7-day duration
            project_id=p2.id, assigned_to=carol.id, title="Checkout UI",
            status=TaskStatus.COMPLETED, estimated_hours=6,
            start_date=date(2026, 8, 1), completed_date=date(2026, 8, 8), deadline=date(2026, 8, 9),
        ),
        "t6": Task(  # carol, P2, blocked, 1 day left -> HIGH risk (blocked escalation)
            project_id=p2.id, assigned_to=carol.id, title="Payment gateway",
            status=TaskStatus.BLOCKED, estimated_hours=2, deadline=date(2026, 8, 15),
        ),
    }
    db_session.add_all(tasks.values())
    db_session.commit()

    updates = [
        DailyUpdate(user_id=alice.id, date=date(2026, 8, 12), tasks_completed=2, tasks_pending=1),
        DailyUpdate(user_id=alice.id, date=date(2026, 8, 13), tasks_completed=1, tasks_pending=2),
        DailyUpdate(user_id=bob.id, date=date(2026, 8, 13), tasks_completed=3, tasks_pending=0),
    ]
    db_session.add_all(updates)
    db_session.commit()

    return {"manager": manager, "alice": alice, "bob": bob, "carol": carol, "p1": p1, "p2": p2, "tasks": tasks}


def test_dashboard_department_filter_scopes_tasks_and_team(db_session):
    seed = _seed(db_session)

    result = get_manager_dashboard(db_session, department="Engineering", as_of=AS_OF)

    # team = alice + bob (Engineering); their tasks are exactly t1-t4 (all in P1)
    assert result.summary.team_size == 2
    assert result.summary.tasks_completed == 1  # only t1
    assert result.summary.tasks_overdue == 1  # t2
    assert result.summary.tasks_at_risk == 1  # t3 (HIGH); t4 is LOW, not counted
    assert result.summary.average_completion_days == pytest.approx(4.0)  # t1: 08-05 - 08-01
    assert result.summary.on_time_completion_rate == pytest.approx(100.0)  # t1 finished on time

    # active (open) hours among t2(3) + t3(2) + t4(4) = 9; capacity = 40*2 = 80 -> 11.25%
    assert result.summary.team_workload.active_hours == pytest.approx(9.0)
    assert result.summary.team_workload.capacity_hours == pytest.approx(80.0)
    assert result.summary.team_workload.utilization_pct == pytest.approx(11.25)

    # overall_team_efficiency must equal the mean of each member's own (unscoped) employee score,
    # exactly matching calculate_team_score's own contract (already unit-tested separately).
    alice_score = calculate_employee_score(db_session, seed["alice"].id, as_of=AS_OF)
    bob_score = calculate_employee_score(db_session, seed["bob"].id, as_of=AS_OF)
    expected_overall = (alice_score.overall_score + bob_score.overall_score) / 2
    assert result.summary.overall_team_efficiency == pytest.approx(expected_overall, rel=1e-6)

    member_ids = {row.user_id for row in result.employee_performance}
    assert member_ids == {seed["alice"].id, seed["bob"].id}


def test_dashboard_project_filter_resolves_team_from_assignees(db_session):
    seed = _seed(db_session)

    result = get_manager_dashboard(db_session, project_id=seed["p2"].id, as_of=AS_OF)

    # No employee/department filter given, so team = distinct assignees in the project = carol only
    assert {row.user_id for row in result.employee_performance} == {seed["carol"].id}
    assert result.summary.tasks_completed == 1  # t5
    assert result.summary.tasks_overdue == 0
    assert result.summary.tasks_at_risk == 1  # t6 (blocked, 1 day left -> HIGH)

    assert len(result.project_progress) == 1
    assert result.project_progress[0].project_id == seed["p2"].id
    assert result.project_progress[0].name == "Storefront"
    # eligible weight = t5(6) + t6(2) = 8; completed weight = 6 -> 75%
    assert result.project_progress[0].progress.progress_pct == pytest.approx(75.0)


def test_dashboard_date_range_uses_deadline_for_overdue_and_completed_date_for_completions(db_session):
    seed = _seed(db_session)

    # Window covers only t2's deadline (08-10) for the deadline-anchored views...
    result = get_manager_dashboard(
        db_session, department="Engineering", date_from=date(2026, 8, 9), date_to=date(2026, 8, 11), as_of=AS_OF
    )
    assert result.summary.tasks_overdue == 1  # t2 deadline=08-10 is in range
    assert result.summary.tasks_at_risk == 0  # t3/t4 deadlines fall outside the window

    # ...but t1's completed_date (08-05) is NOT in that same window, so completions read 0.
    assert result.summary.tasks_completed == 0
    assert result.summary.average_completion_days is None
    assert result.summary.on_time_completion_rate is None

    # A window that instead covers t1's completed_date shows it as completed.
    result2 = get_manager_dashboard(
        db_session, department="Engineering", date_from=date(2026, 8, 4), date_to=date(2026, 8, 6), as_of=AS_OF
    )
    assert result2.summary.tasks_completed == 1
    assert result2.summary.average_completion_days == pytest.approx(4.0)


def test_dashboard_delayed_tasks_and_upcoming_deadlines(db_session):
    seed = _seed(db_session)

    result = get_manager_dashboard(db_session, department="Engineering", as_of=AS_OF)

    assert len(result.delayed_tasks) == 1
    delayed = result.delayed_tasks[0]
    assert delayed.title == "Provision servers"
    assert delayed.delay_days == 4  # 08-14 - 08-10
    assert delayed.delay_reason == "waiting on procurement"
    assert delayed.assignee_name == "Bob"
    assert delayed.project_name == "Platform"

    upcoming_titles = [row.title for row in result.upcoming_deadlines]
    assert upcoming_titles == ["Write migration", "Load testing"]  # sorted soonest-first
    assert result.upcoming_deadlines[0].days_left == 2


def test_dashboard_status_filter_narrows_scope(db_session):
    seed = _seed(db_session)

    result = get_manager_dashboard(db_session, department="Engineering", status=TaskStatus.IN_PROGRESS, as_of=AS_OF)

    assert result.summary.tasks_completed == 0
    assert result.summary.tasks_overdue == 0  # t2 is NOT_STARTED, excluded by the status filter
    assert result.summary.tasks_at_risk == 1  # t3 only (t4 is LOW risk)


def test_calculate_efficiency_trend_aggregates_daily_updates(db_session):
    seed = _seed(db_session)

    trend = calculate_efficiency_trend(
        db_session, user_ids=[seed["alice"].id, seed["bob"].id], date_from=date(2026, 8, 11), date_to=date(2026, 8, 14)
    )

    by_date = {p.date: p for p in trend}
    assert set(by_date) == {date(2026, 8, 12), date(2026, 8, 13)}  # no updates on 08-11/08-14 -> omitted, not zero-filled

    day12 = by_date[date(2026, 8, 12)]
    assert day12.tasks_completed == 2
    assert day12.tasks_pending == 1
    assert day12.avg_completion_ratio == pytest.approx(2 / 3 * 100)
    assert day12.update_count == 1

    # 08-13 has both alice's and bob's updates rolled together
    day13 = by_date[date(2026, 8, 13)]
    assert day13.tasks_completed == 1 + 3
    assert day13.tasks_pending == 2 + 0
    assert day13.update_count == 2


def test_calculate_efficiency_trend_empty_user_ids_returns_empty():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # A trivial session is enough since the function short-circuits before querying.
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    assert calculate_efficiency_trend(session, user_ids=[], date_from=date(2026, 8, 1), date_to=date(2026, 8, 14)) == []
