"""The Autonomous Daily Manager (Phase 10) — the full 11-step workflow, run by
`run_daily_manager()`:

 1. Collect latest daily updates       -> today's `daily_updates` rows
 2. Calculate team metrics             -> `get_manager_dashboard` (Phase 5, unchanged)
 3. Identify significant changes       -> `change_tracking.diff_and_update_issue_state`
 4. Detect workload issues             -> `detection.detect_issues` (Phase 7, unchanged)
 5. Detect deadline risks              -> `detection.detect_issues` (Phase 7, unchanged)
 6. Detect recurring delays            -> `detection.detect_issues` (Phase 7, unchanged)
 7. Analyze project progress           -> `detection.detect_project_risks` (Phase 10, additive)
 8. Generate management summary        -> `report_builder.build_report_data`
 9. Decide whether action is required  -> action_required = any significant change exists
10. Execute only permitted actions     -> `action_policy.decide_and_execute_actions`
11. Record all actions                 -> every action already writes an `AgentAction` (Phase 7
                                          mechanism, reused); this function additionally persists
                                          the whole run as one `DailyManagerReport` row — the
                                          audit record that a run happened at all, even a
                                          "nothing changed today" one.

Steps 4-7 are one call to `snapshot.build_issue_snapshot`, which composes `detect_issues` and
the two Phase 10 detectors into one uniform, severity-tagged list — nothing in this module
computes a metric itself.

"Runs once per working day": `run_date` is unique in `daily_manager_reports`, and this function
checks for an existing row for `as_of` before doing anything else (including before touching
`daily_manager_issue_state` or taking any action) — so calling it twice on the same day is a
safe no-op that returns the first run's report, never a double-alert or a duplicate action.
Weekends are skipped the same way (`is_working_day`). `force=True` bypasses both checks — for
manual re-runs / testing — and replaces that date's existing report if there is one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models.daily_manager import DailyManagerReport
from app.models.daily_update import DailyUpdate
from app.services.analytics.dashboard import get_manager_dashboard
from app.services.daily_manager import queries
from app.services.daily_manager.action_policy import decide_and_execute_actions
from app.services.daily_manager.change_tracking import diff_and_update_issue_state
from app.services.daily_manager.report_builder import build_report_data
from app.services.daily_manager.snapshot import build_issue_snapshot


@dataclass
class DailyManagerRunOutcome:
    status: str  # "ran" | "already_ran" | "skipped_non_working_day"
    report: DailyManagerReport | None


def is_working_day(d: date) -> bool:
    return d.weekday() < 5  # Monday=0 .. Sunday=6; no holiday calendar (see README)


def run_daily_manager(db: Session, as_of: date | None = None, *, force: bool = False) -> DailyManagerRunOutcome:
    as_of = as_of or date.today()

    if not force:
        if not is_working_day(as_of):
            return DailyManagerRunOutcome(status="skipped_non_working_day", report=None)
        existing = queries.get_report_for_date(db, as_of)
        if existing is not None:
            return DailyManagerRunOutcome(status="already_ran", report=existing)
    else:
        existing = queries.get_report_for_date(db, as_of)
        if existing is not None:
            db.delete(existing)
            db.commit()

    # 1. Collect latest daily updates
    updates_today = list(db.scalars(select(DailyUpdate).where(DailyUpdate.date == as_of)))

    # 2. Calculate team metrics
    dashboard_result = get_manager_dashboard(db, as_of=as_of)

    # 4-7. Detect workload issues, deadline risks, recurring delays, project progress
    findings = build_issue_snapshot(db, as_of)

    # 3. Identify significant changes (also upserts daily_manager_issue_state)
    changes = diff_and_update_issue_state(db, findings, as_of)

    # 9. Decide whether action is required
    action_required = len(changes) > 0

    # 10. Execute only permitted actions
    actions_taken = decide_and_execute_actions(db, changes) if action_required else []

    # 8. Generate management summary
    report_data = build_report_data(db, as_of, dashboard_result, findings, changes, len(updates_today), actions_taken)

    # 11. Record all actions -- each action already logged its own AgentAction; persist the run.
    report_row = DailyManagerReport(
        run_date=as_of,
        team_efficiency=dashboard_result.summary.overall_team_efficiency,
        action_required=action_required,
        actions_taken_count=len(actions_taken),
        summary_json=json.dumps(report_data, default=str),
    )
    db.add(report_row)
    db.commit()
    db.refresh(report_row)

    return DailyManagerRunOutcome(status="ran", report=report_row)


def run_daily_manager_standalone(as_of: date | None = None, *, force: bool = False) -> DailyManagerRunOutcome:
    """Entry point for callers with no existing `Session` (the scheduler job) — opens and
    closes its own session via the app's normal `SessionLocal`, same as any other background
    job would.
    """
    db = SessionLocal()
    try:
        return run_daily_manager(db, as_of=as_of, force=force)
    finally:
        db.close()
