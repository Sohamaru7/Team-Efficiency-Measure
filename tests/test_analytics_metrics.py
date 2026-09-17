"""Unit tests for the pure functions in app.services.analytics.metrics.

Every task here is a plain `Task(...)` instance built in memory (no database session, no
commit) — these functions only ever read scalar columns, so this is enough to exercise the
formulas deterministically and cheaply. Expected values are computed by hand in each test's
comment/docstring so the formula being verified is legible without re-deriving it.
"""

from datetime import date

import pytest

from app.models.enums import TaskStatus
from app.models.task import Task
from app.services.analytics.metrics import (
    average_completion_days,
    calculate_project_progress,
    calculate_workload,
    deadline_adherence_rate,
    detect_deadline_risk,
    detect_delays,
    on_time_completion_rate,
    quality_score_metric,
    task_completion_rate,
    task_weight,
    time_efficiency_score,
)
from app.services.analytics.results import DeadlineRiskLevel


def make_task(id, status, **kwargs) -> Task:
    return Task(id=id, project_id=1, title=f"Task {id}", status=status, **kwargs)


# --------------------------------------------------------------------------- task_weight ----


def test_task_weight_uses_estimated_hours():
    t = make_task(1, TaskStatus.NOT_STARTED, estimated_hours=6.5)
    assert task_weight(t) == 6.5


def test_task_weight_falls_back_to_default_when_missing():
    t = make_task(1, TaskStatus.NOT_STARTED, estimated_hours=None)
    assert task_weight(t) == 1.0


def test_task_weight_falls_back_to_default_when_zero():
    t = make_task(1, TaskStatus.NOT_STARTED, estimated_hours=0)
    assert task_weight(t) == 1.0


# ------------------------------------------------------------------- task_completion_rate ----


def test_task_completion_rate_weights_by_estimated_hours_and_excludes_cancelled():
    # actionable = t1(5) + t2(3) + t4(1, no estimate) = weight 9; completed weight = t1(5)
    # rate = 5/9 * 100 = 55.5555...
    tasks = [
        make_task(1, TaskStatus.COMPLETED, estimated_hours=5),
        make_task(2, TaskStatus.IN_PROGRESS, estimated_hours=3),
        make_task(3, TaskStatus.CANCELLED, estimated_hours=100),  # excluded entirely
        make_task(4, TaskStatus.NOT_STARTED, estimated_hours=None),  # weight 1.0
    ]
    assert task_completion_rate(tasks) == pytest.approx(500 / 9, rel=1e-6)


def test_task_completion_rate_none_when_no_actionable_tasks():
    tasks = [make_task(1, TaskStatus.CANCELLED, estimated_hours=10)]
    assert task_completion_rate(tasks) is None


def test_task_completion_rate_empty_list_is_none():
    assert task_completion_rate([]) is None


# ----------------------------------------------------------------- on_time_completion_rate ----


def test_on_time_completion_rate_excludes_no_deadline_and_no_completed_date():
    # eligible = t1(4) + t2(6) = 10; on-time = t1(4) -> 40%
    tasks = [
        make_task(1, TaskStatus.COMPLETED, estimated_hours=4, deadline=date(2026, 8, 10), completed_date=date(2026, 8, 9)),
        make_task(2, TaskStatus.COMPLETED, estimated_hours=6, deadline=date(2026, 8, 10), completed_date=date(2026, 8, 12)),
        make_task(3, TaskStatus.COMPLETED, estimated_hours=4, deadline=None, completed_date=date(2026, 8, 9)),
        make_task(4, TaskStatus.COMPLETED, estimated_hours=4, deadline=date(2026, 8, 5), completed_date=None),
        make_task(5, TaskStatus.IN_PROGRESS, estimated_hours=4, deadline=date(2026, 8, 20)),
    ]
    assert on_time_completion_rate(tasks) == pytest.approx(40.0)


def test_on_time_completion_rate_none_when_no_eligible_tasks():
    tasks = [make_task(1, TaskStatus.IN_PROGRESS, deadline=date(2026, 8, 20))]
    assert on_time_completion_rate(tasks) is None


# ------------------------------------------------------------------- deadline_adherence_rate --


def test_deadline_adherence_rate_covers_open_and_completed_tasks():
    # as_of = 2026-08-14; eligible = t1(4)+t2(6)+t3(5)+t4(3) = 18; adherent = t1(4)+t3(5) = 9
    as_of = date(2026, 8, 14)
    tasks = [
        make_task(1, TaskStatus.COMPLETED, estimated_hours=4, deadline=date(2026, 8, 10), completed_date=date(2026, 8, 9)),  # on time -> adherent
        make_task(2, TaskStatus.COMPLETED, estimated_hours=6, deadline=date(2026, 8, 10), completed_date=date(2026, 8, 12)),  # late -> not adherent
        make_task(3, TaskStatus.IN_PROGRESS, estimated_hours=5, deadline=date(2026, 8, 20)),  # not yet due -> adherent
        make_task(4, TaskStatus.IN_PROGRESS, estimated_hours=3, deadline=date(2026, 8, 1)),  # overdue -> not adherent
        make_task(5, TaskStatus.NOT_STARTED, estimated_hours=10, deadline=None),  # excluded, no deadline
        make_task(6, TaskStatus.CANCELLED, estimated_hours=10, deadline=date(2026, 8, 1)),  # excluded, cancelled
    ]
    assert deadline_adherence_rate(tasks, as_of) == pytest.approx(50.0)


def test_deadline_adherence_rate_treats_missing_completed_date_as_not_adherent():
    as_of = date(2026, 8, 14)
    tasks = [make_task(1, TaskStatus.COMPLETED, estimated_hours=5, deadline=date(2026, 8, 1), completed_date=None)]
    assert deadline_adherence_rate(tasks, as_of) == pytest.approx(0.0)


# --------------------------------------------------------------------- time_efficiency_score --


def test_time_efficiency_score_caps_overachievement_and_scales_overrun():
    # t1 ratio=1.0->100pts, t2 ratio=0.5->50pts, t3 ratio=2.0->capped 100pts; equal weight (4) each
    # weighted avg = (100+50+100)/3 = 83.3333...
    tasks = [
        make_task(1, TaskStatus.COMPLETED, estimated_hours=4, actual_hours=4),
        make_task(2, TaskStatus.COMPLETED, estimated_hours=4, actual_hours=8),
        make_task(3, TaskStatus.COMPLETED, estimated_hours=4, actual_hours=2),
        make_task(4, TaskStatus.COMPLETED, estimated_hours=None, actual_hours=5),  # excluded
        make_task(5, TaskStatus.IN_PROGRESS, estimated_hours=4, actual_hours=4),  # excluded, not completed
    ]
    assert time_efficiency_score(tasks) == pytest.approx(250 / 3, rel=1e-6)


def test_time_efficiency_score_none_when_no_eligible_tasks():
    tasks = [make_task(1, TaskStatus.COMPLETED, estimated_hours=None, actual_hours=None)]
    assert time_efficiency_score(tasks) is None


# ------------------------------------------------------------------------ quality_score_metric


def test_quality_score_metric_weighted_average_excludes_missing():
    # eligible: t1(quality=90, weight5), t2(quality=70, weight3) -> (90*5+70*3)/8 = 82.5
    tasks = [
        make_task(1, TaskStatus.COMPLETED, quality_score=90, estimated_hours=5),
        make_task(2, TaskStatus.COMPLETED, quality_score=70, estimated_hours=3),
        make_task(3, TaskStatus.COMPLETED, quality_score=None, estimated_hours=10),
        make_task(4, TaskStatus.IN_PROGRESS, quality_score=100, estimated_hours=2),
    ]
    assert quality_score_metric(tasks) == pytest.approx(82.5)


def test_quality_score_metric_none_when_no_scores_recorded():
    tasks = [make_task(1, TaskStatus.COMPLETED, quality_score=None)]
    assert quality_score_metric(tasks) is None


# ---------------------------------------------------------------------------- calculate_workload


def test_calculate_workload_under_capacity():
    tasks = [
        make_task(1, TaskStatus.NOT_STARTED, estimated_hours=10),
        make_task(2, TaskStatus.IN_PROGRESS, estimated_hours=15),
        make_task(3, TaskStatus.BLOCKED, estimated_hours=5),
        make_task(4, TaskStatus.COMPLETED, estimated_hours=100),  # not open, excluded
        make_task(5, TaskStatus.CANCELLED, estimated_hours=50),  # not open, excluded
    ]
    result = calculate_workload(tasks, capacity_hours=40.0)
    assert result.active_hours == 30.0
    assert result.utilization_pct == pytest.approx(75.0)
    assert result.score == pytest.approx(75.0)
    assert result.active_task_count == 3


def test_calculate_workload_overloaded_is_penalized_symmetrically():
    tasks = [make_task(1, TaskStatus.IN_PROGRESS, estimated_hours=30)]
    result = calculate_workload(tasks, capacity_hours=20.0)  # 150% utilization
    assert result.utilization_pct == pytest.approx(150.0)
    assert result.score == pytest.approx(50.0)  # 100 - (150-100)


def test_calculate_workload_extreme_overload_floors_at_zero():
    tasks = [make_task(1, TaskStatus.IN_PROGRESS, estimated_hours=60)]
    result = calculate_workload(tasks, capacity_hours=20.0)  # 300% utilization
    assert result.utilization_pct == pytest.approx(300.0)
    assert result.score == 0.0


def test_calculate_workload_idle_scores_zero_not_none():
    result = calculate_workload([], capacity_hours=40.0)
    assert result.active_hours == 0.0
    assert result.utilization_pct == 0.0
    assert result.score == 0.0
    assert result.active_task_count == 0


# ------------------------------------------------------------------ calculate_project_progress


def test_calculate_project_progress_weighted_and_excludes_cancelled():
    # eligible weight = 10+5+5 = 20; completed weight = 10 -> 50%
    tasks = [
        make_task(1, TaskStatus.COMPLETED, estimated_hours=10),
        make_task(2, TaskStatus.IN_PROGRESS, estimated_hours=5),
        make_task(3, TaskStatus.NOT_STARTED, estimated_hours=5),
        make_task(4, TaskStatus.CANCELLED, estimated_hours=100),
    ]
    result = calculate_project_progress(tasks, project_id=7)
    assert result.project_id == 7
    assert result.progress_pct == pytest.approx(50.0)
    assert result.total_tasks == 3
    assert result.completed_tasks == 1
    assert result.in_progress_tasks == 1
    assert result.not_started_tasks == 1
    assert result.cancelled_tasks == 1


def test_calculate_project_progress_empty_project_is_zero_not_none():
    result = calculate_project_progress([], project_id=9)
    assert result.progress_pct == 0.0
    assert result.total_tasks == 0


# -------------------------------------------------------------------------- detect_deadline_risk


@pytest.mark.parametrize(
    "status,deadline,expected_risk",
    [
        (TaskStatus.COMPLETED, date(2026, 8, 10), DeadlineRiskLevel.NONE),
        (TaskStatus.CANCELLED, date(2026, 8, 10), DeadlineRiskLevel.NONE),
        (TaskStatus.NOT_STARTED, None, DeadlineRiskLevel.NONE),
        (TaskStatus.NOT_STARTED, date(2026, 8, 10), DeadlineRiskLevel.OVERDUE),  # -4 days
        (TaskStatus.NOT_STARTED, date(2026, 8, 15), DeadlineRiskLevel.HIGH),  # 1 day left
        (TaskStatus.NOT_STARTED, date(2026, 8, 16), DeadlineRiskLevel.HIGH),  # 2 days left
        (TaskStatus.NOT_STARTED, date(2026, 8, 18), DeadlineRiskLevel.MEDIUM),  # 4 days left
        (TaskStatus.NOT_STARTED, date(2026, 8, 19), DeadlineRiskLevel.MEDIUM),  # 5 days left
        (TaskStatus.NOT_STARTED, date(2026, 8, 25), DeadlineRiskLevel.LOW),  # 11 days left
        (TaskStatus.IN_PROGRESS, date(2026, 8, 14), DeadlineRiskLevel.HIGH),  # due today, 0 days left
    ],
)
def test_detect_deadline_risk_classification(status, deadline, expected_risk):
    as_of = date(2026, 8, 14)
    tasks = [make_task(1, status, deadline=deadline)]
    [result] = detect_deadline_risk(tasks, as_of)
    assert result.risk == expected_risk


def test_detect_deadline_risk_escalates_blocked_tasks():
    as_of = date(2026, 8, 14)
    # blocked with <=5 days left -> HIGH even though a non-blocked task at that distance is MEDIUM
    close = make_task(1, TaskStatus.BLOCKED, deadline=date(2026, 8, 18))  # 4 days left
    far = make_task(2, TaskStatus.BLOCKED, deadline=date(2026, 9, 1))  # 18 days left
    close_risk, far_risk = detect_deadline_risk([close, far], as_of)
    assert close_risk.risk == DeadlineRiskLevel.HIGH
    assert far_risk.risk == DeadlineRiskLevel.MEDIUM


def test_detect_deadline_risk_sorted_most_severe_first():
    as_of = date(2026, 8, 14)
    tasks = [
        make_task(1, TaskStatus.NOT_STARTED, deadline=date(2026, 8, 25)),  # LOW
        make_task(2, TaskStatus.NOT_STARTED, deadline=date(2026, 8, 10)),  # OVERDUE
        make_task(3, TaskStatus.COMPLETED, deadline=date(2026, 8, 1)),  # NONE
        make_task(4, TaskStatus.NOT_STARTED, deadline=date(2026, 8, 15)),  # HIGH
    ]
    results = detect_deadline_risk(tasks, as_of)
    assert [r.risk for r in results] == [
        DeadlineRiskLevel.OVERDUE,
        DeadlineRiskLevel.HIGH,
        DeadlineRiskLevel.LOW,
        DeadlineRiskLevel.NONE,
    ]


# -------------------------------------------------------------------------------- detect_delays


def test_detect_delays_covers_completed_and_open_tasks():
    as_of = date(2026, 8, 14)
    tasks = [
        make_task(1, TaskStatus.COMPLETED, deadline=date(2026, 8, 10), completed_date=date(2026, 8, 12), delay_reason="reviewer was slow"),
        make_task(2, TaskStatus.COMPLETED, deadline=date(2026, 8, 10), completed_date=date(2026, 8, 8)),
        make_task(3, TaskStatus.COMPLETED, deadline=date(2026, 8, 10), completed_date=None),
        make_task(4, TaskStatus.IN_PROGRESS, deadline=date(2026, 8, 10)),
        make_task(5, TaskStatus.IN_PROGRESS, deadline=date(2026, 8, 20)),
        make_task(6, TaskStatus.CANCELLED, deadline=date(2026, 8, 1)),
        make_task(7, TaskStatus.NOT_STARTED, deadline=None),
    ]
    results = {r.task_id: r for r in detect_delays(tasks, as_of)}

    assert results[1].is_delayed is True
    assert results[1].delay_days == 2
    assert results[1].delay_reason == "reviewer was slow"

    assert results[2].is_delayed is False
    assert results[2].delay_days == -2

    assert results[3].is_delayed is False
    assert results[3].delay_days is None

    assert results[4].is_delayed is True
    assert results[4].delay_days == 4

    assert results[5].is_delayed is False
    assert results[5].delay_days == -6

    assert results[6].is_delayed is False
    assert results[6].delay_days is None

    assert results[7].is_delayed is False
    assert results[7].delay_days is None


def test_detect_delays_filterable_to_only_delayed():
    as_of = date(2026, 8, 14)
    tasks = [
        make_task(1, TaskStatus.IN_PROGRESS, deadline=date(2026, 8, 10)),  # delayed
        make_task(2, TaskStatus.IN_PROGRESS, deadline=date(2026, 8, 20)),  # not delayed
    ]
    only_delayed = [r for r in detect_delays(tasks, as_of) if r.is_delayed]
    assert [r.task_id for r in only_delayed] == [1]


# ------------------------------------------------------------------------ average_completion_days


def test_average_completion_days_plain_unweighted_mean():
    # durations: 4 days, 2 days, 10 days -> mean = 16/3 = 5.3333...
    tasks = [
        make_task(1, TaskStatus.COMPLETED, start_date=date(2026, 8, 1), completed_date=date(2026, 8, 5), estimated_hours=100),
        make_task(2, TaskStatus.COMPLETED, start_date=date(2026, 8, 1), completed_date=date(2026, 8, 3), estimated_hours=1),
        make_task(3, TaskStatus.COMPLETED, start_date=date(2026, 8, 1), completed_date=date(2026, 8, 11), estimated_hours=1),
        make_task(4, TaskStatus.COMPLETED, start_date=None, completed_date=date(2026, 8, 5)),  # excluded, no start_date
        make_task(5, TaskStatus.IN_PROGRESS, start_date=date(2026, 8, 1), completed_date=None),  # excluded, not completed
    ]
    # Deliberately large estimated_hours on task 1 to prove this is NOT weighted like the score
    # components — a weighted mean would skew heavily toward 4 days; the plain mean is 5.33.
    assert average_completion_days(tasks) == pytest.approx(16 / 3, rel=1e-6)


def test_average_completion_days_none_when_no_eligible_tasks():
    tasks = [make_task(1, TaskStatus.IN_PROGRESS, start_date=date(2026, 8, 1))]
    assert average_completion_days(tasks) is None
