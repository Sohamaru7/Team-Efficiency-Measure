from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class DailyManagerReportSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_date: date
    generated_at: datetime
    team_efficiency: Optional[float] = None
    action_required: bool
    actions_taken_count: int


class DailyManagerReportDetailSchema(DailyManagerReportSummarySchema):
    daily_updates_collected: int
    major_changes: list[dict[str, Any]]
    completed_work: list[dict[str, Any]]
    delayed_work: list[dict[str, Any]]
    at_risk_deadlines: list[dict[str, Any]]
    workload_problems: list[dict[str, Any]]
    quality_issues: list[dict[str, Any]]
    project_risks: list[dict[str, Any]]
    recurring_delay_causes: list[dict[str, Any]]
    performance_drops: list[dict[str, Any]]
    recommended_actions: list[str]
    actions_taken: list[dict[str, Any]]


class DailyManagerRunResponse(BaseModel):
    status: str  # "ran" | "already_ran" | "skipped_non_working_day"
    report: Optional[DailyManagerReportDetailSchema] = None
