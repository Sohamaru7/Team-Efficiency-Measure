from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.analytics import EmployeeScoreSchema, ProjectProgressSchema, WorkloadSchema


class EmployeePerformanceRowSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    name: str
    department: Optional[str] = None
    score: EmployeeScoreSchema


class WorkloadRowSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    name: str
    department: Optional[str] = None
    workload: WorkloadSchema


class ProjectProgressRowSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    name: str
    progress: ProjectProgressSchema


class DelayedTaskRowSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    title: str
    project_id: int
    project_name: str
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    status: str
    deadline: Optional[date] = None
    delay_days: Optional[int] = None
    delay_reason: Optional[str] = None


class UpcomingDeadlineRowSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    title: str
    project_id: int
    project_name: str
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    status: str
    priority: str
    deadline: date
    days_left: int


class TrendPointSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    avg_completion_ratio: Optional[float] = None
    tasks_completed: int
    tasks_pending: int
    update_count: int


class DashboardSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of: date
    team_size: int
    overall_team_efficiency: Optional[float] = None
    tasks_completed: int
    tasks_overdue: int
    tasks_at_risk: int
    average_completion_days: Optional[float] = None
    on_time_completion_rate: Optional[float] = None
    team_workload: WorkloadSchema


class ManagerDashboardSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of: date
    filters: dict[str, object]
    summary: DashboardSummarySchema
    employee_performance: list[EmployeePerformanceRowSchema]
    workload_distribution: list[WorkloadRowSchema]
    project_progress: list[ProjectProgressRowSchema]
    delayed_tasks: list[DelayedTaskRowSchema]
    upcoming_deadlines: list[UpcomingDeadlineRowSchema]
    efficiency_trend: list[TrendPointSchema]
