from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.daily_manager import DailyManagerReport


def get_report_for_date(db: Session, run_date: date) -> DailyManagerReport | None:
    stmt = select(DailyManagerReport).where(DailyManagerReport.run_date == run_date)
    return db.scalars(stmt).first()


def get_report(db: Session, report_id: int) -> DailyManagerReport | None:
    return db.get(DailyManagerReport, report_id)


def get_latest_report(db: Session) -> DailyManagerReport | None:
    stmt = select(DailyManagerReport).order_by(DailyManagerReport.run_date.desc()).limit(1)
    return db.scalars(stmt).first()


def list_reports(db: Session, skip: int = 0, limit: int = 30) -> list[DailyManagerReport]:
    stmt = select(DailyManagerReport).order_by(DailyManagerReport.run_date.desc()).offset(skip).limit(limit)
    return list(db.scalars(stmt))
