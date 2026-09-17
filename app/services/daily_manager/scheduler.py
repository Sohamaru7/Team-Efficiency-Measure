"""Optional in-process scheduler for the Autonomous Daily Manager. Off by default
(`settings.DAILY_MANAGER_SCHEDULER_ENABLED`) so the app — and the test suite, which shares this
same `Settings` object and boots the same FastAPI `lifespan` via `TestClient` — never starts a
background thread unexpectedly. `POST /api/daily-manager/run` always works as a manual trigger
regardless of this setting; enabling the scheduler only adds the "runs by itself every working
morning" behavior on top of that.

Uses APScheduler's `BackgroundScheduler` (a plain thread, not asyncio-integrated) specifically
so it can't interfere with FastAPI's own event loop. The job itself is idempotent
(`run_daily_manager`'s "already ran today" / "not a working day" checks), so even if the
scheduler fires more than once (e.g. a fast restart) nothing is double-alerted or double-acted.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.services.daily_manager.orchestrator import run_daily_manager_standalone

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_job() -> None:
    try:
        outcome = run_daily_manager_standalone()
        logger.info("Daily manager scheduled run: %s", outcome.status)
    except Exception:  # noqa: BLE001 — a scheduled job must never crash the scheduler thread
        logger.exception("Daily manager scheduled run failed")


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if not settings.DAILY_MANAGER_SCHEDULER_ENABLED:
        return None
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _run_job,
        CronTrigger(day_of_week="mon-fri", hour=settings.DAILY_MANAGER_RUN_HOUR, minute=0),
        id="daily_manager_run",
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Daily manager scheduler started: weekdays at %02d:00 UTC", settings.DAILY_MANAGER_RUN_HOUR)
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
