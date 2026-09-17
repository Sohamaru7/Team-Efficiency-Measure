"""Autonomous Daily Manager (Phase 10): a scheduled workflow that collects the day's signals,
detects and classifies issues, decides whether a manager needs to know, executes only the
narrow set of low-risk/approval-gated actions it's allowed to, and records everything.

- `snapshot.py` — steps 4-7 (workload/deadline/recurring-delay/project-risk detection),
  composing `app.services.ai.detection` (Phase 7, unchanged) + two additive Phase 10 detectors.
- `change_tracking.py` — step 3 (significant-change detection against persisted issue state).
- `report_builder.py` — step 8 (assembles the report payload).
- `action_policy.py` — steps 9-10 (decide + execute only permitted actions, via the exact same
  `app.services.ai.actions` functions the chat assistant uses).
- `orchestrator.py` — `run_daily_manager()`, the top-level pipeline (all 11 steps) + step 11's
  run-level audit record (`DailyManagerReport`).
- `scheduler.py` — optional in-process "once per working day" trigger (off by default).
"""

from app.services.daily_manager.orchestrator import DailyManagerRunOutcome, run_daily_manager

__all__ = ["run_daily_manager", "DailyManagerRunOutcome"]
