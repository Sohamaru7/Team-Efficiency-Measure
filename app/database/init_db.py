import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password, validate_password_strength
from app.database.base import Base
from app.database.session import SessionLocal

# Imported for side effects: registers all models on Base.metadata.
from app.models import *  # noqa: F401,F403
from app.models.enums import UserRole
from app.models.user import User

logger = logging.getLogger(__name__)


def init_db() -> None:
    """Ensure models are registered on Base.metadata.

    As of Phase 2, table creation/upgrades are owned by Alembic migrations
    (see migrations/), not by Base.metadata.create_all(). Run
    `alembic upgrade head` to create or update database tables.
    """


def bootstrap_admin() -> None:
    """One-time convenience: create the very first admin account from
    `ADMIN_BOOTSTRAP_EMAIL`/`ADMIN_BOOTSTRAP_PASSWORD` if both are set and no admin exists yet.
    Solves the chicken-and-egg problem of "you need an admin to create the first admin" without
    a hardcoded default credential anywhere in source control. A no-op (by design, not by
    error) whenever either setting is blank, or an admin already exists — safe to call on every
    startup. Never raises past a database-connectivity failure — same "app must still start
    even if the DB is unreachable" resilience every other phase already relies on; the caller
    (`app.main`'s lifespan) wraps this the same way it wraps `init_db()`.
    """
    if not (settings.ADMIN_BOOTSTRAP_EMAIL and settings.ADMIN_BOOTSTRAP_PASSWORD):
        return

    db = SessionLocal()
    try:
        existing_admin = db.scalars(select(User).where(User.role == UserRole.ADMIN)).first()
        if existing_admin is not None:
            return

        validate_password_strength(settings.ADMIN_BOOTSTRAP_PASSWORD)
        admin = User(
            name="Admin",
            email=settings.ADMIN_BOOTSTRAP_EMAIL,
            role=UserRole.ADMIN,
            hashed_password=hash_password(settings.ADMIN_BOOTSTRAP_PASSWORD),
        )
        db.add(admin)
        db.commit()
        logger.warning(
            "Bootstrapped initial admin account (%s) from ADMIN_BOOTSTRAP_EMAIL/PASSWORD. "
            "Unset these in .env once you no longer need first-run bootstrap.",
            settings.ADMIN_BOOTSTRAP_EMAIL,
        )
    finally:
        db.close()
