import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routes import (
    ai_assistant,
    analytics,
    auth,
    daily_manager,
    daily_updates,
    dashboard,
    data_export,
    data_import,
    emails,
    health,
    pages,
    performance_scores,
    projects,
    tasks,
    users,
)
from app.core.config import settings
from app.core.error_handlers import register_error_handlers
from app.core.middleware import register_security_headers
from app.core.rate_limit import limiter
from app.database.init_db import bootstrap_admin, init_db
from app.services.daily_manager.scheduler import shutdown_scheduler, start_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
        bootstrap_admin()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Database initialization skipped: %s", exc)
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

register_security_headers(app)
register_error_handlers(app)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(health.router)
app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(daily_updates.router)
app.include_router(performance_scores.router)
app.include_router(analytics.router)
app.include_router(dashboard.router)
app.include_router(ai_assistant.router)
app.include_router(data_import.router)
app.include_router(data_export.router)
app.include_router(emails.router)
app.include_router(daily_manager.router)
