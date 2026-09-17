"""Smoke tests for app.services.daily_manager.scheduler — verifies the scheduler stays off by
default (so the test suite / a default deployment never starts a background thread
unexpectedly) and that enabling it actually schedules a job, without waiting for a real
cron tick to fire.
"""

from app.core.config import settings
from app.services.daily_manager import scheduler as scheduler_module


def test_scheduler_disabled_by_default():
    assert settings.DAILY_MANAGER_SCHEDULER_ENABLED is False


def test_start_scheduler_noop_when_disabled():
    result = scheduler_module.start_scheduler()
    assert result is None
    assert scheduler_module._scheduler is None


def test_start_scheduler_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "DAILY_MANAGER_SCHEDULER_ENABLED", True)
    try:
        result = scheduler_module.start_scheduler()
        assert result is not None
        assert result.get_job("daily_manager_run") is not None
        # Calling start again while already running returns the same instance, doesn't double-add.
        again = scheduler_module.start_scheduler()
        assert again is result
    finally:
        scheduler_module.shutdown_scheduler()


def test_shutdown_scheduler_is_safe_when_never_started():
    scheduler_module._scheduler = None
    scheduler_module.shutdown_scheduler()  # must not raise
    assert scheduler_module._scheduler is None
