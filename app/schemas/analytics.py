from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.services.analytics.results import DeadlineRiskLevel


class WorkloadSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    active_hours: float
    capacity_hours: float
    utilization_pct: float
    score: float
    active_task_count: int


class ProjectProgressSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    progress_pct: float
    total_weight: float
    completed_weight: float
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    blocked_tasks: int
    not_started_tasks: int
    cancelled_tasks: int


class TaskDeadlineRiskSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    title: str
    status: str
    deadline: Optional[date] = None
    days_left: Optional[int] = None
    risk: DeadlineRiskLevel
    reason: str


class TaskDelaySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    title: str
    status: str
    deadline: Optional[date] = None
    is_delayed: bool
    delay_days: Optional[int] = None
    delay_reason: Optional[str] = None


class ScoreComponentSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value: Optional[float] = None
    weight: float
    applied_weight: float
    sample_size: int


class EmployeeScoreSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    as_of: date
    overall_score: Optional[float] = None
    components: dict[str, ScoreComponentSchema]
    task_counts: dict[str, int]
    workload: WorkloadSchema
    projects_considered: list[int]


class TeamScoreSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of: date
    member_count: int
    scored_member_count: int
    overall_score: Optional[float] = None
    component_averages: dict[str, Optional[float]]
    members: list[EmployeeScoreSchema]
