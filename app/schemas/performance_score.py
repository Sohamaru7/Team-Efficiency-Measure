from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PerformanceScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    period: str
    completion_score: Optional[Decimal] = None
    timeliness_score: Optional[Decimal] = None
    quality_score: Optional[Decimal] = None
    time_efficiency_score: Optional[Decimal] = None
    workload_score: Optional[Decimal] = None
    overall_score: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime
