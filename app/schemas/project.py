from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ProjectStatus


class ProjectBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    manager_id: Optional[int] = None
    start_date: Optional[date] = None
    deadline: Optional[date] = None
    status: ProjectStatus = ProjectStatus.PLANNING

    @model_validator(mode="after")
    def validate_dates(self) -> "ProjectBase":
        if self.start_date and self.deadline and self.deadline < self.start_date:
            raise ValueError("deadline must be on or after start_date")
        return self


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    manager_id: Optional[int] = None
    start_date: Optional[date] = None
    deadline: Optional[date] = None
    status: Optional[ProjectStatus] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "ProjectUpdate":
        if self.start_date and self.deadline and self.deadline < self.start_date:
            raise ValueError("deadline must be on or after start_date")
        return self


class ProjectRead(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
