from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.schemas.health import DatabaseHealthResponse, HealthResponse
from app.services.health_service import check_database_connection

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok", app_name=settings.APP_NAME, version="0.1.0")


@router.get("/db", response_model=DatabaseHealthResponse)
def database_health_check(db: Session = Depends(get_db)) -> DatabaseHealthResponse:
    is_healthy, detail = check_database_connection(db)
    return DatabaseHealthResponse(status="ok" if is_healthy else "error", detail=detail)
