"""Integration tests for the DB-aware orchestration functions in
app.services.analytics.scoring, against a realistic seeded SQLite dataset (via the shared
`db_session` fixture — same in-memory DB the CRUD API tests use).

`test_calculate_employee_score_matches_hand_computed_weighted_average` independently
recomputes the expected overall score from the same weight constants the code uses, rather than
just asserting "some number came back" — the goal is to catch a wiring bug (wrong tasks fetched,
wrong weight applied) as well as a formula bug.
"""

from datetime import date

import pytest

from app.models.enums import ProjectStatus, TaskPriority, TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.analytics.constants import INDIVIDUAL_SCORE_WEIGHTS
from app.services.analytics.scoring import calculate_employee_score, calculate_team_score

AS_OF = date(2026, 8, 14)


def _seed_realistic_dataset(db_session):
    manager = User(name="Priya Shah", email="priya@example.com", role=UserRole.MANAGER, department="Engineering")
    alice = User(name="Alice", email="alice@example.com", role=UserRole.EMPLOYEE, department="Engineering")
    bob = User(name="Bob", email="bob@example.com", role=UserRole.EMPLOYEE, department="Engineering")
    db_session.add_all([manager, alice, bob])
    db_session.commit()

    p1 = Project(name="Website Revamp", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    p2 = Project(name="Data Pipeline", manager_id=manager.id, status=ProjectStatus.ACTIVE)
    db_session.add_all([p1, p2])
    db_session.commit()

    tasks = [
        # P1 / Alice: on-time + a late one
        Task(
            project_id=p1.id, assigned_to=alice.id, title="Design homepage", priority=TaskPriority.HIGH,
            status=TaskStatus.COMPLETED, estimated_hours=4, actual_hours=4, quality_score=90,
            deadline=date(2026, 8, 10), completed_date=date(2026, 8, 9),
        ),
        Task(
            project_id=p1.id, assigned_to=alice.id, title="Build checkout flow", priority=TaskPriority.HIGH,
            status=TaskStatus.COMPLETED, estimated_hours=6, actual_hours=8, quality_score=70,
            deadline=date(2026, 8, 12), completed_date=date(2026, 8, 13),  # finished 1 day late
        ),
        Task(
            project_id=p1.id, assigned_to=alice.id, title="Write API docs", priority=TaskPriority.MEDIUM,
            status=TaskStatus.IN_PROGRESS, estimated_hours=5, deadline=date(2026, 8, 20),  # not yet due
        ),
        # P2 / Alice: overdue, not started
        Task(
            project_id=p2.id, assigned_to=alice.id, title="Migrate schema", priority=TaskPriority.URGENT,
            status=TaskStatus.NOT_STARTED, estimated_hours=3, deadline=date(2026, 8, 1),  # overdue
        ),
        # P2 / unassigned but still part of the project (affects P2's project-wide progress)
        Task(
            project_id=p2.id, assigned_to=None, title="Set up warehouse", priority=TaskPriority.MEDIUM,
            status=TaskStatus.COMPLETED, estimated_hours=10, actual_hours=10,
        ),
    ]
    db_session.add_all(tasks)
    db_session.commit()

    return {"manager": manager, "alice": alice, "bob": bob, "p1": p1, "p2": p2}


def test_calculate_employee_score_matches_hand_computed_weighted_average(db_session):
    seed = _seed_realistic_dataset(db_session)

    result = calculate_employee_score(db_session, seed["alice"].id, as_of=AS_OF)

    # completion: actionable weight = 4+6+5+3 = 18; completed weight = 4+6 = 10 -> 55.5556
    expected_completion = 1000 / 18
    # on_time: eligible (completed w/ deadline+completed_date) weight = 4+6 = 10; on-time = task1 (4) -> 40
    expected_on_time = 40.0
    # quality: eligible weight = 4+6 = 10; weighted = (90*4 + 70*6)/10 = 78
    expected_quality = 78.0
    # time_efficiency: task1 ratio=1.0->100pts(w4), task2 ratio=6/8=0.75->75pts(w6); (100*4+75*6)/10=85
    expected_time_efficiency = 85.0
    # deadline_adherence: eligible weight=4+6+5+3=18; adherent = task1(4, on time) + task3(5, not yet due) = 9 -> 50
    expected_deadline_adherence = 50.0
    # project_progress: P1 eligible weight=4+6+5=15, completed=10 -> 66.6667
    #                   P2 eligible weight=3+10=13, completed=10 -> 76.9231; average of the two
    expected_p1_progress = 1000 / 15
    expected_p2_progress = 1000 / 13
    expected_project_progress = (expected_p1_progress + expected_p2_progress) / 2
    # workload: open tasks assigned to Alice = task3(5) + task4(3) = 8; 8/40*100 = 20
    expected_workload = 20.0

    assert result.components["completion"].value == pytest.approx(expected_completion, rel=1e-6)
    assert result.components["on_time"].value == pytest.approx(expected_on_time)
    assert result.components["quality"].value == pytest.approx(expected_quality)
    assert result.components["time_efficiency"].value == pytest.approx(expected_time_efficiency)
    assert result.components["deadline_adherence"].value == pytest.approx(expected_deadline_adherence)
    assert result.components["project_progress"].value == pytest.approx(expected_project_progress, rel=1e-6)
    assert result.components["workload"].value == pytest.approx(expected_workload)
    assert result.workload.active_task_count == 2
    assert sorted(result.projects_considered) == sorted([seed["p1"].id, seed["p2"].id])

    expected_overall = (
        expected_completion * INDIVIDUAL_SCORE_WEIGHTS["completion"]
        + expected_on_time * INDIVIDUAL_SCORE_WEIGHTS["on_time"]
        + expected_quality * INDIVIDUAL_SCORE_WEIGHTS["quality"]
        + expected_time_efficiency * INDIVIDUAL_SCORE_WEIGHTS["time_efficiency"]
        + expected_deadline_adherence * INDIVIDUAL_SCORE_WEIGHTS["deadline_adherence"]
        + expected_project_progress * INDIVIDUAL_SCORE_WEIGHTS["project_progress"]
        + expected_workload * INDIVIDUAL_SCORE_WEIGHTS["workload"]
    )
    assert result.overall_score == pytest.approx(expected_overall, rel=1e-6)

    # All 7 weights were available (nothing missing), so applied_weight == nominal weight.
    for name, weight in INDIVIDUAL_SCORE_WEIGHTS.items():
        assert result.components[name].applied_weight == pytest.approx(weight)

    assert result.task_counts["total"] == 4
    assert result.task_counts["completed"] == 2
    assert result.task_counts["in_progress"] == 1
    assert result.task_counts["not_started"] == 1


def test_calculate_employee_score_renormalizes_when_components_missing(db_session):
    seed = _seed_realistic_dataset(db_session)
    bob = seed["bob"]

    # Bob has exactly one task: completed, no quality_score, no actual_hours, no deadline.
    # completion is defined (1/1 -> 100); on_time/quality/time_efficiency/deadline_adherence
    # are all None (no eligible data); project_progress is defined (his one project);
    # workload is defined (0 active tasks -> 0).
    task = Task(
        project_id=seed["p1"].id, assigned_to=bob.id, title="Quick fix",
        status=TaskStatus.COMPLETED, estimated_hours=2,
    )
    db_session.add(task)
    db_session.commit()

    result = calculate_employee_score(db_session, bob.id, as_of=AS_OF)

    assert result.components["completion"].value == pytest.approx(100.0)
    assert result.components["on_time"].value is None
    assert result.components["quality"].value is None
    assert result.components["time_efficiency"].value is None
    assert result.components["deadline_adherence"].value is None
    assert result.components["project_progress"].value is not None
    assert result.components["workload"].value == pytest.approx(0.0)

    # Only completion, project_progress and workload contributed -> their weights should have
    # been renormalized (proportionally scaled up) so they still sum to 1.0.
    available = ["completion", "project_progress", "workload"]
    applied_sum = sum(result.components[name].applied_weight for name in available)
    assert applied_sum == pytest.approx(1.0)
    for name in ("on_time", "quality", "time_efficiency", "deadline_adherence"):
        assert result.components[name].applied_weight == 0.0

    # Renormalized weight ratios should match the ratios of the nominal weights among
    # the available components.
    nominal_sum = sum(INDIVIDUAL_SCORE_WEIGHTS[name] for name in available)
    for name in available:
        expected_applied = INDIVIDUAL_SCORE_WEIGHTS[name] / nominal_sum
        assert result.components[name].applied_weight == pytest.approx(expected_applied)

    assert result.overall_score is not None
    expected_overall = sum(
        result.components[name].value * result.components[name].applied_weight for name in available
    )
    assert result.overall_score == pytest.approx(expected_overall, rel=1e-6)


def test_calculate_employee_score_zero_tasks_yields_workload_only_score(db_session):
    idle_user = User(name="Idle Ida", email="ida@example.com", department="Engineering")
    db_session.add(idle_user)
    db_session.commit()

    result = calculate_employee_score(db_session, idle_user.id, as_of=AS_OF)

    for name in ("completion", "on_time", "quality", "time_efficiency", "deadline_adherence", "project_progress"):
        assert result.components[name].value is None
    assert result.components["workload"].value == pytest.approx(0.0)
    assert result.components["workload"].applied_weight == pytest.approx(1.0)
    assert result.overall_score == pytest.approx(0.0)
    assert result.projects_considered == []


def test_calculate_team_score_with_explicit_user_ids(db_session):
    seed = _seed_realistic_dataset(db_session)

    result = calculate_team_score(db_session, user_ids=[seed["alice"].id, seed["bob"].id], as_of=AS_OF)

    assert result.member_count == 2
    assert result.scored_member_count == 2
    assert len(result.members) == 2
    assert result.overall_score is not None

    # Bob has zero tasks in this dataset, so his overall is the workload-only score (0.0),
    # same as test_calculate_employee_score_zero_tasks_yields_workload_only_score above.
    alice_result = calculate_employee_score(db_session, seed["alice"].id, as_of=AS_OF)
    expected_team_overall = (alice_result.overall_score + 0.0) / 2
    assert result.overall_score == pytest.approx(expected_team_overall, rel=1e-6)


def test_calculate_team_score_filters_by_department(db_session):
    seed = _seed_realistic_dataset(db_session)
    other_dept = User(name="Sam Sales", email="sam@example.com", department="Sales")
    db_session.add(other_dept)
    db_session.commit()

    result = calculate_team_score(db_session, department="Engineering", as_of=AS_OF)

    member_ids = {m.user_id for m in result.members}
    assert other_dept.id not in member_ids
    assert seed["alice"].id in member_ids
    assert seed["bob"].id in member_ids
    assert seed["manager"].id in member_ids  # manager is also in Engineering department


def test_calculate_team_score_defaults_to_all_active_users(db_session):
    seed = _seed_realistic_dataset(db_session)
    inactive = User(name="Gone Gary", email="gary@example.com", active=False)
    db_session.add(inactive)
    db_session.commit()

    result = calculate_team_score(db_session, as_of=AS_OF)

    member_ids = {m.user_id for m in result.members}
    assert inactive.id not in member_ids
    assert seed["alice"].id in member_ids
