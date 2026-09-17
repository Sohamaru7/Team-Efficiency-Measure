from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str


class DatabaseHealthResponse(BaseModel):
    status: str
    detail: str
