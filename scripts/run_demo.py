"""Runs a disposable, self-contained demo instance of the app:

- **Demo mode is on** (`DEMO_MODE=true`) — the login page offers one-click "Enter Demo" buttons
  (Admin/Manager/Employee) that need no password at all. Role-based access control itself is
  NOT disabled: an Admin demo login simply has nothing to be blocked from (the same rule that
  applies to any real admin account), which is what "the system, unblocked" actually means here
  — see `app/api/routes/auth.py`'s `demo_login` docstring for the exact guarantee.
- **SQLite, not PostgreSQL** — no database setup required. A fresh `demo.db` file is created
  (overwriting any previous one) and seeded with a realistic multi-department dataset every
  time this script starts, so every demo begins from the same known-good state.

Usage:
    python scripts/run_demo.py

Then open http://127.0.0.1:8100/login and click "Enter Demo (full access)".

This script is for local demoing only — never point it at a real database, and never set
DEMO_MODE=true outside of what this script does for you automatically.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Must be set before app.core.config is imported anywhere (pydantic-settings reads the
# environment/`.env` at Settings() construction time). Explicitly blanking the bootstrap-admin
# settings matters even if you don't have them set: if a real `.env` in this directory has them
# configured (e.g. for your normal Postgres-backed dev setup), this demo must NOT inherit that
# and attempt to bootstrap an admin against your real database — it forces a self-contained,
# SQLite-only run regardless of what else is in `.env`.
os.environ["DEMO_MODE"] = "true"
os.environ["ADMIN_BOOTSTRAP_EMAIL"] = ""
os.environ["ADMIN_BOOTSTRAP_PASSWORD"] = ""

DEMO_DB_PATH = PROJECT_ROOT / "demo.db"
DEMO_DB_PATH.unlink(missing_ok=True)  # always start a demo from a clean, known-good dataset

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.models  # noqa: E402,F401  (registers all models on Base.metadata)
from app.core.security import hash_password  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.database.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import (  # noqa: E402
    EmailDirection,
    ProjectStatus,
    TaskPriority,
    TaskStatus,
    UserRole,
)
from app.models.daily_update import DailyUpdate  # noqa: E402
from app.models.email import Email  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.models.user import User  # noqa: E402

engine = create_engine(f"sqlite:///{DEMO_DB_PATH}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _enable_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _get_db


def seed() -> None:
    db = SessionLocal()
    today = date.today()

    manager = User(
        name="Priya Manager", email="priya@demo.example.com", role=UserRole.MANAGER,
        department="Engineering", hashed_password=hash_password("demopass123"),
    )
    alice = User(
        name="Alice Chen", email="alice@demo.example.com", role=UserRole.EMPLOYEE,
        department="Engineering", hashed_password=hash_password("demopass123"),
    )
    bob = User(
        name="Bob Diaz", email="bob@demo.example.com", role=UserRole.EMPLOYEE,
        department="Engineering", hashed_password=hash_password("demopass123"),
    )
    sales_manager = User(
        name="Sam Sales", email="sam@demo.example.com", role=UserRole.MANAGER,
        department="Sales", hashed_password=hash_password("demopass123"),
    )
    carol = User(
        name="Carol Nguyen", email="carol@demo.example.com", role=UserRole.EMPLOYEE,
        department="Sales", hashed_password=hash_password("demopass123"),
    )
    db.add_all([manager, alice, bob, sales_manager, carol])
    db.commit()

    website = Project(
        name="Website Revamp", manager_id=manager.id, status=ProjectStatus.ACTIVE,
        start_date=today - timedelta(days=30), deadline=today + timedelta(days=14),
        description="Rebuild the marketing site on the new design system.",
    )
    mobile = Project(
        name="Mobile App Launch", manager_id=manager.id, status=ProjectStatus.ACTIVE,
        start_date=today - timedelta(days=10), deadline=today + timedelta(days=3),
        description="Ship v1 of the companion mobile app.",
    )
    campaign = Project(
        name="Q3 Campaign", manager_id=sales_manager.id, status=ProjectStatus.ACTIVE,
        start_date=today - timedelta(days=20), deadline=today + timedelta(days=20),
    )
    db.add_all([website, mobile, campaign])
    db.commit()

    tasks = [
        Task(project_id=website.id, assigned_to=alice.id, title="Design new homepage", status=TaskStatus.COMPLETED,
             priority=TaskPriority.HIGH, estimated_hours=16, actual_hours=14,
             start_date=today - timedelta(days=20), deadline=today - timedelta(days=10),
             completed_date=today - timedelta(days=9), quality_score=92),
        Task(project_id=website.id, assigned_to=alice.id, title="Rebuild pricing page", status=TaskStatus.IN_PROGRESS,
             priority=TaskPriority.HIGH, estimated_hours=12, actual_hours=6,
             start_date=today - timedelta(days=5), deadline=today + timedelta(days=1)),
        Task(project_id=website.id, assigned_to=alice.id, title="Migrate blog content", status=TaskStatus.IN_PROGRESS,
             priority=TaskPriority.MEDIUM, estimated_hours=10, actual_hours=8,
             start_date=today - timedelta(days=5), deadline=today + timedelta(days=1)),
        Task(project_id=website.id, assigned_to=alice.id, title="SEO audit", status=TaskStatus.IN_PROGRESS,
             priority=TaskPriority.LOW, estimated_hours=8, actual_hours=2,
             start_date=today - timedelta(days=2), deadline=today + timedelta(days=10)),
        Task(project_id=website.id, assigned_to=alice.id, title="Accessibility pass", status=TaskStatus.NOT_STARTED,
             priority=TaskPriority.MEDIUM, estimated_hours=6, start_date=today, deadline=today + timedelta(days=12)),
        Task(project_id=mobile.id, assigned_to=bob.id, title="Set up CI pipeline", status=TaskStatus.COMPLETED,
             priority=TaskPriority.MEDIUM, estimated_hours=8, actual_hours=10,
             start_date=today - timedelta(days=9), deadline=today - timedelta(days=2),
             completed_date=today - timedelta(days=1), quality_score=48,
             delay_reason="waiting for client to confirm App Store account access"),
        Task(project_id=mobile.id, assigned_to=bob.id, title="Push notifications", status=TaskStatus.BLOCKED,
             priority=TaskPriority.URGENT, estimated_hours=10,
             start_date=today - timedelta(days=3), deadline=today + timedelta(days=2),
             delay_reason="waiting for client design sign-off"),
        Task(project_id=campaign.id, assigned_to=carol.id, title="Draft campaign copy", status=TaskStatus.IN_PROGRESS,
             priority=TaskPriority.MEDIUM, estimated_hours=6, actual_hours=3,
             start_date=today - timedelta(days=2), deadline=today + timedelta(days=5)),
    ]
    db.add_all(tasks)
    db.commit()

    db.add_all([
        Email(
            task_id=tasks[6].id, project_id=mobile.id, subject="Re: Push notification design",
            from_address="client@bigcorp.example.com", to_addresses="priya@demo.example.com",
            direction=EmailDirection.INBOUND, is_external=True, linked_by=manager.id,
            sent_at=datetime.combine(today - timedelta(days=1), datetime.min.time()),
            body_text="Still reviewing internally, will confirm design sign-off by end of week.",
        ),
    ])

    for i, (user, completed, pending) in enumerate([(alice, 1, 3), (bob, 0, 2), (carol, 1, 1)]):
        db.add(DailyUpdate(
            user_id=user.id, date=today - timedelta(days=i + 1), tasks_completed=completed, tasks_pending=pending,
            notes="Making steady progress." if completed else "Blocked, see task notes.",
        ))
    db.commit()

    from app.services.ai import actions as ai_actions

    ai_actions.assign_task(
        db, task_id=tasks[4].id, employee_id=bob.id,
        reason="Demo: proposed reassignment awaiting manager approval — try Approve/Reject on the AI Assistant page.",
    )

    from app.services.daily_manager.orchestrator import run_daily_manager

    run_daily_manager(db, as_of=today, force=True)

    db.close()
    print("Seeded demo.db with a multi-department dataset (Engineering + Sales).")


if __name__ == "__main__":
    import uvicorn

    seed()
    print()
    print("Demo mode is ON. Open http://127.0.0.1:8100/login and click 'Enter Demo (full access)'.")
    print("(Real accounts also work, e.g. priya@demo.example.com / demopass123.)")
    print()
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="warning")
