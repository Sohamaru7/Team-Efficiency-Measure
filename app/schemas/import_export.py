from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ImportRowResultSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_number: int
    status: str  # "accepted" | "rejected" | "duplicate"
    employee: Optional[str] = None
    task: Optional[str] = None
    project: Optional[str] = None
    errors: list[str] = []
    task_id: Optional[int] = None


class ImportResultSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    filename: str
    dry_run: bool
    column_mapping: dict[str, Optional[str]]
    rows_processed: int
    rows_accepted: int
    rows_rejected: int
    rows_duplicate: int
    rows: list[ImportRowResultSchema] = []
    file_error: Optional[str] = None
    history_id: Optional[int] = None


class ImportHistorySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    imported_by: Optional[int] = None
    timestamp: datetime
    rows_processed: int
    rows_accepted: int
    rows_rejected: int
    errors: Optional[str] = None
