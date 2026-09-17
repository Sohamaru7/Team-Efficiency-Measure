"""Plain dataclasses returned by the analytics package.

Kept as dataclasses (not Pydantic models) so `metrics.py`/`scoring.py` stay framework-free and
reusable outside of a FastAPI request (e.g. from a script or a future batch job). The API layer
(`app/schemas/analytics.py`) wraps these with `model_validate(..., from_attributes=True)`.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date


class DeadlineRiskLevel(str, enum.Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    OVERDUE = "overdue"


@dataclass
class WorkloadResult:
    """See metrics.calculate_workload for the formula."""

    active_hours: float
    capacity_hours: float
    utilization_pct: float  # uncapped — can exceed 100 when overloaded
    score: float  # 0-100, shaped to penalize both idling and overload
    active_task_count: int


@dataclass
class ProjectProgressResult:
    """See metrics.calculate_project_progress for the formula."""

    project_id: int
    progress_pct: float  # 0-100, difficulty-weighted
    total_weight: float
    completed_weight: float
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    blocked_tasks: int
    not_started_tasks: int
    cancelled_tasks: int


@dataclass
class TaskDeadlineRisk:
    """One task's forward-looking deadline-risk classification. See metrics.detect_deadline_risk."""

    task_id: int
    title: str
    status: str
    deadline: date | None
    days_left: int | None  # negative once overdue; None if the task has no deadline
    risk: DeadlineRiskLevel
    reason: str


@dataclass
class TaskDelay:
    """One task's actual (not predicted) delay status. See metrics.detect_delays."""

    task_id: int
    title: str
    status: str
    deadline: date | None
    is_delayed: bool
    delay_days: int | None  # days late so far (open tasks) or days late at completion
    delay_reason: str | None  # the human-entered Task.delay_reason, if any


@dataclass
class ScoreComponent:
    """One weighted ingredient of an employee score."""

    value: float | None  # 0-100, or None if there was no data to compute it
    weight: float  # nominal weight from INDIVIDUAL_SCORE_WEIGHTS
    applied_weight: float  # weight actually used after renormalizing away missing components
    sample_size: int  # number of tasks/projects that contributed to `value`


@dataclass
class EmployeeScoreResult:
    user_id: int
    as_of: date
    overall_score: float | None
    components: dict[str, ScoreComponent]
    task_counts: dict[str, int]
    workload: WorkloadResult
    projects_considered: list[int] = field(default_factory=list)


@dataclass
class TeamScoreResult:
    as_of: date
    member_count: int
    scored_member_count: int
    overall_score: float | None
    component_averages: dict[str, float | None]
    members: list[EmployeeScoreResult] = field(default_factory=list)
