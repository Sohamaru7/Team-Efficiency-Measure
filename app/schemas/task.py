from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import TaskPriority, TaskStatus


class TaskBase(BaseModel):
    project_id: int
    assigned_to: Optional[int] = None
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    priority: TaskPriority = TaskPriority.MEDIUM
    estimated_hours: Optional[Decimal] = Field(default=None, ge=0)
    actual_hours: Optional[Decimal] = Field(default=None, ge=0)
    start_date: Optional[date] = None
    deadline: Optional[date] = None
    completed_date: Optional[date] = None
    status: TaskStatus = TaskStatus.NOT_STARTED
    quality_score: Optional[Decimal] = Field(default=None, ge=0, le=100)
    delay_reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "TaskBase":
        if self.start_date and self.deadline and self.deadline < self.start_date:
            raise ValueError("deadline must be on or after start_date")
        return self


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    project_id: Optional[int] = None
    assigned_to: Optional[int] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None
    estimated_hours: Optional[Decimal] = Field(default=None, ge=0)
    actual_hours: Optional[Decimal] = Field(default=None, ge=0)
    start_date: Optional[date] = None
    deadline: Optional[date] = None
    completed_date: Optional[date] = None
    status: Optional[TaskStatus] = None
    quality_score: Optional[Decimal] = Field(default=None, ge=0, le=100)
    delay_reason: Optional[str] = None
    changed_by: Optional[int] = Field(
        default=None,
        description="User id attributed to this change, recorded in task history when status changes.",
    )

    @model_validator(mode="after")
    def validate_dates(self) -> "TaskUpdate":
        if self.start_date and self.deadline and self.deadline < self.start_date:
            raise ValueError("deadline must be on or after start_date")
        return self


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
