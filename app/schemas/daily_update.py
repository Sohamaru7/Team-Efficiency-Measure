from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DailyUpdateBase(BaseModel):
    user_id: int
    date: date
    tasks_completed: int = Field(default=0, ge=0)
    tasks_pending: int = Field(default=0, ge=0)
    blockers: Optional[str] = None
    notes: Optional[str] = None


class DailyUpdateCreate(DailyUpdateBase):
    pass


class DailyUpdateUpdate(BaseModel):
    date: Optional[date] = None
    tasks_completed: Optional[int] = Field(default=None, ge=0)
    tasks_pending: Optional[int] = Field(default=None, ge=0)
    blockers: Optional[str] = None
    notes: Optional[str] = None


class DailyUpdateRead(DailyUpdateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
