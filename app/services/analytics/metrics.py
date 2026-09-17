"""Pure, deterministic metric functions.

Every function here takes an already-fetched sequence of `Task`-like objects (any object with
the same attributes as `app.models.task.Task` works — the unit tests build plain `Task(...)`
instances without a database session) and returns a plain number or dataclass. No function in
this module opens a database session, calls an external service, or uses an LLM. Given the same
inputs, every function returns the same output every time.

All rate/score metrics are expressed on a 0-100 scale. A metric returns `None` (not 0) when
there is no eligible data to compute it from — e.g. a brand-new employee with zero tasks has an
undefined "on-time completion rate," which is different from a *bad* one. Callers (see
`scoring.py`) treat `None` as "exclude this component and renormalize remaining weights," not as
zero.

## Difficulty weighting

Per the Phase 4 brief ("account for task difficulty/estimated hours ... instead of treating
every task equally"), every aggregate metric below weights each task by `task_weight(task)`
instead of counting tasks 1-for-1. A task's weight is its `estimated_hours` when set, or
`DEFAULT_TASK_WEIGHT` (1.0) when not. This has a useful side effect: if *no* task in a group has
an estimate, every task falls back to the same weight and the formula degrades gracefully to a
plain (unweighted) count-based rate — no separate "no data" branch is needed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from app.models.enums import TaskStatus
from app.services.analytics.constants import (
    DEADLINE_RISK_HIGH_DAYS,
    DEADLINE_RISK_MEDIUM_DAYS,
    DEFAULT_CAPACITY_HOURS,
    DEFAULT_TASK_WEIGHT,
)
from app.services.analytics.results import (
    DeadlineRiskLevel,
    ProjectProgressResult,
    TaskDeadlineRisk,
    TaskDelay,
    WorkloadResult,
)

OPEN_STATUSES = (TaskStatus.NOT_STARTED, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)


class TaskLike(Protocol):
    """Structural type documenting exactly what these functions read off a task.

    Anything with these attributes works — a real `Task` ORM instance, a `Task(...)`
    constructed in a test without a session, or a hand-rolled stand-in.
    """

    id: int
    title: str
    status: TaskStatus
    estimated_hours: object  # Decimal | float | None
    actual_hours: object  # Decimal | float | None
    quality_score: object  # Decimal | float | None
    start_date: date | None
    deadline: date | None
    completed_date: date | None
    delay_reason: str | None


def _num(value: object) -> float | None:
    """Coerce a Decimal/float/int/None field to float. SQLAlchemy Numeric columns come back
    as `decimal.Decimal`, which cannot be mixed with `float` in arithmetic without an explicit
    conversion (`Decimal('1') / 2.0` raises `TypeError`) — every metric funnels numeric task
    fields through this helper for that reason.
    """
    if value is None:
        return None
    return float(value)


def task_weight(task: TaskLike) -> float:
    """A task's contribution to a weighted average: its estimated hours, or
    `DEFAULT_TASK_WEIGHT` when no estimate was recorded. See module docstring.
    """
    hours = _num(task.estimated_hours)
    if hours is not None and hours > 0:
        return hours
    return DEFAULT_TASK_WEIGHT


def _weighted_rate(numerator_tasks: Sequence[TaskLike], denominator_tasks: Sequence[TaskLike]) -> float | None:
    """sum(weight(t) for t in numerator) / sum(weight(t) for t in denominator), as 0-100.

    `numerator_tasks` must be a subset of `denominator_tasks`. Returns None if the denominator
    is empty (nothing eligible to measure).
    """
    denom = sum(task_weight(t) for t in denominator_tasks)
    if denom <= 0:
        return None
    numer = sum(task_weight(t) for t in numerator_tasks)
    return (numer / denom) * 100.0


def task_completion_rate(tasks: Sequence[TaskLike]) -> float | None:
    """1. Task completion rate.

    Difficulty-weighted share of a person's *actionable* tasks that are COMPLETED.

    actionable = every task except CANCELLED ones (a cancelled task was removed from scope
    by someone else's decision — it should not count against the assignee).

        rate = Σ weight(t) for t in actionable if t.status == COMPLETED
               ─────────────────────────────────────────────────────────  × 100
               Σ weight(t) for t in actionable

    None if there are no actionable tasks.
    """
    actionable = [t for t in tasks if t.status != TaskStatus.CANCELLED]
    completed = [t for t in actionable if t.status == TaskStatus.COMPLETED]
    return _weighted_rate(completed, actionable)


def on_time_completion_rate(tasks: Sequence[TaskLike]) -> float | None:
    """2. On-time completion rate.

    Of the COMPLETED tasks that had a deadline *and* a recorded completion date, the
    difficulty-weighted share finished on or before that deadline. This metric only judges
    already-finished work — it looks backward, unlike deadline adherence (below), which also
    looks at tasks still open.

    eligible = completed tasks with deadline is not None and completed_date is not None
    on_time  = eligible tasks where completed_date <= deadline

        rate = Σ weight(t) for t in on_time / Σ weight(t) for t in eligible × 100

    Tasks with no deadline, or completed without a completed_date being recorded, are excluded
    entirely (there's nothing to judge them against) rather than counted as failures. None if
    there are no eligible tasks.
    """
    completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
    eligible = [t for t in completed if t.deadline is not None and t.completed_date is not None]
    on_time = [t for t in eligible if t.completed_date <= t.deadline]
    return _weighted_rate(on_time, eligible)


def deadline_adherence_rate(tasks: Sequence[TaskLike], as_of: date) -> float | None:
    """3. Deadline adherence.

    A forward-looking counterpart to on-time completion: across every non-cancelled task that
    has a deadline (finished or not), is it currently on track?

    eligible = non-cancelled tasks with deadline is not None
    adherent, per task:
      - COMPLETED with a completed_date  -> adherent iff completed_date <= deadline
      - COMPLETED without a completed_date -> not adherent (can't verify; conservative)
      - not completed (open)             -> adherent iff as_of <= deadline (not yet overdue)

        rate = Σ weight(t) for t in adherent / Σ weight(t) for t in eligible × 100

    Unlike on-time completion rate, an open task that has simply blown its deadline drags this
    metric down immediately, without waiting for it to eventually be marked complete. None if
    there are no eligible tasks.
    """
    eligible = [t for t in tasks if t.status != TaskStatus.CANCELLED and t.deadline is not None]

    def is_adherent(t: TaskLike) -> bool:
        if t.status == TaskStatus.COMPLETED:
            return t.completed_date is not None and t.completed_date <= t.deadline
        return as_of <= t.deadline

    adherent = [t for t in eligible if is_adherent(t)]
    return _weighted_rate(adherent, eligible)


def time_efficiency_score(tasks: Sequence[TaskLike]) -> float | None:
    """4. Time efficiency.

    How closely actual effort matched estimated effort, for COMPLETED tasks that have both
    `estimated_hours` and a positive `actual_hours`.

    Per task:
        ratio  = estimated_hours / actual_hours
        points = min(ratio, 1.0) × 100

    - ratio == 1.0 (spot-on estimate)          -> 100 points
    - ratio  > 1.0 (finished faster than est.) -> capped at 100 — we don't reward beating the
      estimate beyond full marks, which would otherwise incentivize inflating estimates or
      rushing/cutting quality to "win" this metric
    - ratio  < 1.0 (took longer than estimate) -> scaled down proportionally, approaching 0 as
      actual_hours grows much larger than estimated_hours

    The weighted average across eligible tasks uses `task_weight` (their `estimated_hours`),
    so a large overrun on a big task moves this score more than the same overrun on a trivial
    one. None if no eligible tasks (nothing completed has both hour fields recorded).
    """
    eligible = []
    points_by_task: dict[int, float] = {}
    for t in tasks:
        if t.status != TaskStatus.COMPLETED:
            continue
        est = _num(t.estimated_hours)
        act = _num(t.actual_hours)
        if est is None or act is None or est <= 0 or act <= 0:
            continue
        ratio = est / act
        points_by_task[id(t)] = min(ratio, 1.0) * 100.0
        eligible.append(t)

    if not eligible:
        return None

    weight_total = sum(task_weight(t) for t in eligible)
    if weight_total <= 0:
        return None
    weighted_points = sum(points_by_task[id(t)] * task_weight(t) for t in eligible)
    return weighted_points / weight_total


def quality_score_metric(tasks: Sequence[TaskLike]) -> float | None:
    """5. Quality score.

    Difficulty-weighted average of the human-recorded `quality_score` (already 0-100) across
    COMPLETED tasks that have one set. Tasks without a recorded quality score are excluded —
    absence of a rating is not assumed to mean 0 (poor) or 100 (perfect). None if no completed
    task has a quality score yet.
    """
    eligible = [
        t for t in tasks if t.status == TaskStatus.COMPLETED and _num(t.quality_score) is not None
    ]
    if not eligible:
        return None
    weight_total = sum(task_weight(t) for t in eligible)
    if weight_total <= 0:
        return None
    weighted_sum = sum(_num(t.quality_score) * task_weight(t) for t in eligible)
    return weighted_sum / weight_total


def calculate_workload(
    tasks: Sequence[TaskLike], capacity_hours: float = DEFAULT_CAPACITY_HOURS
) -> WorkloadResult:
    """6. Workload utilization.

    Compares a person's currently *open* workload (NOT_STARTED, IN_PROGRESS, or BLOCKED tasks)
    against an expected capacity for the period (default 40 hours = one standard work week;
    pass a different `capacity_hours` for a different period length).

        active_hours     = Σ weight(t) for t in tasks if t.status in {NOT_STARTED, IN_PROGRESS, BLOCKED}
        utilization_pct  = active_hours / capacity_hours × 100          (uncapped)

    The 0-100 `score` used in the overall weighted average shapes utilization so that *both*
    idling and overload are penalized, peaking at exactly full capacity:

        utilization_pct <= 100:  score = utilization_pct
            (no active work -> 0; fully booked -> 100)
        utilization_pct  > 100:  score = max(0, 100 - (utilization_pct - 100))
            (every point of overload above 100% costs a point, reaching 0 at 200% —
             mirrors the idle side and reflects that sustained overload risks burnout/quality)

    Unlike the rate metrics above, workload is always defined (0 active tasks still yields a
    valid 0% utilization / 0 score), so this never returns None.
    """
    active = [t for t in tasks if t.status in OPEN_STATUSES]
    active_hours = sum(task_weight(t) for t in active)
    utilization_pct = (active_hours / capacity_hours * 100.0) if capacity_hours > 0 else 0.0

    return WorkloadResult(
        active_hours=active_hours,
        capacity_hours=capacity_hours,
        utilization_pct=utilization_pct,
        score=workload_score_from_utilization(utilization_pct),
        active_task_count=len(active),
    )


def workload_score_from_utilization(utilization_pct: float) -> float:
    """The 0-100 shaping formula documented in `calculate_workload`, factored out so callers
    that aggregate utilization across a group (e.g. a manager dashboard's team-wide workload
    tile in `dashboard.py`) can apply the exact same scoring rule without duplicating it.
    """
    if utilization_pct <= 100.0:
        return utilization_pct
    return max(0.0, 100.0 - (utilization_pct - 100.0))


def average_completion_days(tasks: Sequence[TaskLike]) -> float | None:
    """Average completion time (a plain descriptive statistic, not a weighted score).

    The mean number of calendar days from `start_date` to `completed_date`, across COMPLETED
    tasks that have both. Unlike the scoring components above, this is a simple (unweighted)
    mean rather than a difficulty-weighted one — "tasks take 4.2 days on average" is meant to
    read as a plain calendar statistic on a dashboard tile; task difficulty is already captured
    separately by `time_efficiency_score`. None if no completed task has both dates recorded.
    """
    durations = [
        (t.completed_date - t.start_date).days
        for t in tasks
        if t.status == TaskStatus.COMPLETED and t.start_date is not None and t.completed_date is not None
    ]
    if not durations:
        return None
    return sum(durations) / len(durations)


def calculate_project_progress(tasks: Sequence[TaskLike], project_id: int) -> ProjectProgressResult:
    """7. Project progress.

    Difficulty-weighted completion percentage for one project, using every non-cancelled task
    in it (regardless of assignee — this is a project-level metric, not a personal one):

        eligible      = tasks in the project with status != CANCELLED
        progress_pct  = Σ weight(t) for t in eligible if t.status == COMPLETED
                         ───────────────────────────────────────────────────── × 100
                         Σ weight(t) for t in eligible

    Weighting by estimated hours means a project isn't reported "50% done" just because half of
    a long tail of small tasks are finished while one large task is untouched.

    A project with zero eligible tasks reports progress_pct = 0.0 (not None) — an empty project
    is meaningfully "0% done," which is a different situation from an employee having no tasks
    to compute a personal rate from.
    """
    eligible = [t for t in tasks if t.status != TaskStatus.CANCELLED]
    completed = [t for t in eligible if t.status == TaskStatus.COMPLETED]

    total_weight = sum(task_weight(t) for t in eligible)
    completed_weight = sum(task_weight(t) for t in completed)
    progress_pct = (completed_weight / total_weight * 100.0) if total_weight > 0 else 0.0

    def count(status: TaskStatus) -> int:
        return sum(1 for t in tasks if t.status == status)

    return ProjectProgressResult(
        project_id=project_id,
        progress_pct=progress_pct,
        total_weight=total_weight,
        completed_weight=completed_weight,
        total_tasks=len(eligible),
        completed_tasks=len(completed),
        in_progress_tasks=count(TaskStatus.IN_PROGRESS),
        blocked_tasks=count(TaskStatus.BLOCKED),
        not_started_tasks=count(TaskStatus.NOT_STARTED),
        cancelled_tasks=count(TaskStatus.CANCELLED),
    )


def _classify_single(task: TaskLike, as_of: date) -> tuple[DeadlineRiskLevel, str, int | None]:
    if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
        return DeadlineRiskLevel.NONE, "Task is already finished; no deadline risk.", None

    if task.deadline is None:
        return DeadlineRiskLevel.NONE, "No deadline set.", None

    days_left = (task.deadline - as_of).days

    if days_left < 0:
        return DeadlineRiskLevel.OVERDUE, f"{-days_left} day(s) past deadline.", days_left

    if task.status == TaskStatus.BLOCKED:
        if days_left <= DEADLINE_RISK_MEDIUM_DAYS:
            return (
                DeadlineRiskLevel.HIGH,
                f"Blocked with only {days_left} day(s) left before deadline.",
                days_left,
            )
        return (
            DeadlineRiskLevel.MEDIUM,
            "Blocked task; deadline is not immediately close but progress is stalled.",
            days_left,
        )

    if days_left <= DEADLINE_RISK_HIGH_DAYS:
        return DeadlineRiskLevel.HIGH, f"Only {days_left} day(s) left before deadline.", days_left

    if days_left <= DEADLINE_RISK_MEDIUM_DAYS:
        return DeadlineRiskLevel.MEDIUM, f"{days_left} day(s) left before deadline.", days_left

    return DeadlineRiskLevel.LOW, f"{days_left} day(s) left before deadline; on track.", days_left


def detect_deadline_risk(
    tasks: Sequence[TaskLike], as_of: date | None = None
) -> list[TaskDeadlineRisk]:
    """9/10. Deadline risk detection (forward-looking).

    Classifies every task's deadline risk *as of* a given date (defaults to today):

    - NONE:    already finished (completed/cancelled), or has no deadline
    - OVERDUE: open task past its deadline
    - HIGH:    <= DEADLINE_RISK_HIGH_DAYS days left (default 2), OR a BLOCKED task with
               <= DEADLINE_RISK_MEDIUM_DAYS days left — a stalled task close to its deadline is
               high risk regardless of the exact day count
    - MEDIUM:  <= DEADLINE_RISK_MEDIUM_DAYS days left (default 5), OR any BLOCKED task further
               out — being blocked at all is inherently risky since no progress is being made
    - LOW:     more time left than the thresholds above, and not blocked

    Returns one `TaskDeadlineRisk` per input task (including NONE-risk ones), sorted most-severe
    first (OVERDUE > HIGH > MEDIUM > LOW > NONE) so callers can `[:n]` for "top risks" or filter
    by `.risk`.
    """
    as_of = as_of or date.today()
    severity_order = {
        DeadlineRiskLevel.OVERDUE: 0,
        DeadlineRiskLevel.HIGH: 1,
        DeadlineRiskLevel.MEDIUM: 2,
        DeadlineRiskLevel.LOW: 3,
        DeadlineRiskLevel.NONE: 4,
    }
    results = []
    for t in tasks:
        risk, reason, days_left = _classify_single(t, as_of)
        results.append(
            TaskDeadlineRisk(
                task_id=t.id,
                title=t.title,
                status=t.status.value if hasattr(t.status, "value") else str(t.status),
                deadline=t.deadline,
                days_left=days_left,
                risk=risk,
                reason=reason,
            )
        )
    results.sort(key=lambda r: severity_order[r.risk])
    return results


def detect_delays(tasks: Sequence[TaskLike], as_of: date | None = None) -> list[TaskDelay]:
    """Delay detection (actual, not predicted).

    Distinct from `detect_deadline_risk`: this reports tasks that *are* (or *were*) actually
    late, not tasks merely at risk of becoming late.

    For each non-cancelled task with a deadline:
      - COMPLETED with a completed_date: delay_days = (completed_date - deadline).days;
        is_delayed iff delay_days > 0 (positive = finished late, zero/negative = on time/early)
      - COMPLETED without a completed_date: cannot verify -> not delayed, delay_days = None
      - open (not completed): delay_days = (as_of - deadline).days;
        is_delayed iff delay_days > 0 (positive = overdue by that many days, zero/negative =
        days still remaining before the deadline)

    Tasks without a deadline, or CANCELLED, are not delayed (there is nothing to be late
    against, or the task is out of scope) and get delay_days = None.

    Returns one `TaskDelay` per input task passed in (so callers can inspect any task
    uniformly); filter the result by `.is_delayed` for just the currently/previously late ones.
    The task's own human-entered `delay_reason` is always surfaced when present, independent of
    whether this function's own computation agrees a delay occurred (e.g. it may explain a delay
    against an *earlier* deadline that was since pushed out).
    """
    as_of = as_of or date.today()
    results = []
    for t in tasks:
        status_value = t.status.value if hasattr(t.status, "value") else str(t.status)
        if t.status == TaskStatus.CANCELLED or t.deadline is None:
            results.append(
                TaskDelay(
                    task_id=t.id,
                    title=t.title,
                    status=status_value,
                    deadline=t.deadline,
                    is_delayed=False,
                    delay_days=None,
                    delay_reason=t.delay_reason,
                )
            )
            continue

        if t.status == TaskStatus.COMPLETED:
            if t.completed_date is None:
                is_delayed, delay_days = False, None
            else:
                # Positive = finished late, zero/negative = on time or early.
                delay_days = (t.completed_date - t.deadline).days
                is_delayed = delay_days > 0
        else:
            # Positive = overdue by this many days, zero/negative = days still remaining.
            delay_days = (as_of - t.deadline).days
            is_delayed = delay_days > 0

        results.append(
            TaskDelay(
                task_id=t.id,
                title=t.title,
                status=status_value,
                deadline=t.deadline,
                is_delayed=is_delayed,
                delay_days=delay_days,
                delay_reason=t.delay_reason,
            )
        )
    return results
