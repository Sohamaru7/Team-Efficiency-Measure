import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_manager_or_admin
from app.database.session import get_db
from app.models.daily_manager import DailyManagerReport
from app.models.user import User
from app.schemas.daily_manager import (
    DailyManagerReportDetailSchema,
    DailyManagerReportSummarySchema,
    DailyManagerRunResponse,
)
from app.services.daily_manager import queries
from app.services.daily_manager.orchestrator import run_daily_manager

router = APIRouter(prefix="/api/daily-manager", tags=["daily-manager"])


def _to_detail_schema(record: DailyManagerReport) -> DailyManagerReportDetailSchema:
    data = json.loads(record.summary_json)
    return DailyManagerReportDetailSchema(
        id=record.id,
        run_date=record.run_date,
        generated_at=record.generated_at,
        team_efficiency=float(record.team_efficiency) if record.team_efficiency is not None else None,
        action_required=record.action_required,
        actions_taken_count=record.actions_taken_count,
        daily_updates_collected=data.get("daily_updates_collected", 0),
        major_changes=data.get("major_changes", []),
        completed_work=data.get("completed_work", []),
        delayed_work=data.get("delayed_work", []),
        at_risk_deadlines=data.get("at_risk_deadlines", []),
        workload_problems=data.get("workload_problems", []),
        quality_issues=data.get("quality_issues", []),
        project_risks=data.get("project_risks", []),
        recurring_delay_causes=data.get("recurring_delay_causes", []),
        performance_drops=data.get("performance_drops", []),
        recommended_actions=data.get("recommended_actions", []),
        actions_taken=data.get("actions_taken", []),
    )


@router.post("/run", response_model=DailyManagerRunResponse)
def trigger_run(
    as_of: date | None = Query(default=None, description="Date to run for. Omit for today."),
    force: bool = Query(default=False, description="Bypass the working-day and already-ran checks."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_admin),
) -> DailyManagerRunResponse:
    """Manually trigger the Autonomous Daily Manager's full 11-step workflow. This is what the
    optional scheduler (`app.services.daily_manager.scheduler`, off by default) calls once per
    working morning — this endpoint exists so a manager (or a real cron/Task Scheduler entry)
    can trigger the same run on demand. Calling it twice for the same date without `force` is a
    safe no-op (`status: "already_ran"`) — nothing is re-alerted or re-actioned.
    """
    outcome = run_daily_manager(db, as_of=as_of, force=force)
    return DailyManagerRunResponse(status=outcome.status, report=_to_detail_schema(outcome.report) if outcome.report else None)


@router.get("/reports", response_model=list[DailyManagerReportSummarySchema])
def list_reports(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_admin),
) -> list[DailyManagerReportSummarySchema]:
    return [DailyManagerReportSummarySchema.model_validate(r) for r in queries.list_reports(db, skip=skip, limit=limit)]


@router.get("/reports/latest", response_model=DailyManagerReportDetailSchema)
def get_latest_report(
    db: Session = Depends(get_db), current_user: User = Depends(require_manager_or_admin)
) -> DailyManagerReportDetailSchema:
    record = queries.get_latest_report(db)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No daily manager reports yet.")
    return _to_detail_schema(record)


@router.get("/reports/{report_id}", response_model=DailyManagerReportDetailSchema)
def get_report(
    report_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_manager_or_admin)
) -> DailyManagerReportDetailSchema:
    record = queries.get_report(db, report_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    return _to_detail_schema(record)
