import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.api.deps import get_current_user
from app.core.rate_limit import limiter
from app.database.base import Base
from app.database.session import get_db
from app.main import app
from app.models.enums import UserRole
from app.models.user import User

TEST_ADMIN_EMAIL = "test-admin@example.com"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """The rate limiter (see app.core.rate_limit) is a module-level singleton keyed by client
    IP — TestClient always presents the same fake IP, so without a reset its in-memory counters
    would accumulate *across* tests within the same run, making an unrelated later test fail
    with 429 because an earlier test (e.g. the brute-force one in test_auth.py) used up the
    quota. Reset before every test so each one starts with a clean limit window.
    """
    limiter.reset()
    yield


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


def _get_or_create_test_admin(db: Session) -> User:
    user = db.query(User).filter_by(email=TEST_ADMIN_EMAIL).first()
    if user is None:
        user = User(name="Test Admin", email=TEST_ADMIN_EMAIL, role=UserRole.ADMIN, active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@pytest.fixture()
def client(db_engine):
    """A TestClient authenticated, by default, as a fixed admin user — mirrors the existing
    `get_db` override (a real in-memory DB standing in for Postgres): here, a real admin
    `User` row standing in for a real login, so the ~350 tests written before this
    production-readiness pass (which exercise business logic, not the auth/authorization layer
    itself) don't all need an `Authorization` header added. Admin bypasses every role/ownership
    check in `app.services.authz`, so this is equivalent to "no restriction" for those tests —
    exactly the access level they were written assuming.

    Authentication and authorization *themselves* are tested for real in `test_auth.py` and
    `test_authz.py`/`test_authorization_boundaries.py`, using `client_as` / `unauthenticated_client`
    below, which do not take this shortcut.
    """
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def _override_get_db():
        session = testing_session_local()
        try:
            yield session
        finally:
            session.close()

    def _override_get_current_user(db: Session = Depends(get_db)) -> User:
        return _get_or_create_test_admin(db)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def client_as(client):
    """`client_as(some_user)` makes subsequent requests on `client` authenticate as that user
    instead of the default test admin — re-fetching it fresh from each request's own database
    session (never holding onto a single possibly-stale/detached ORM instance across requests),
    the same way the real `get_current_user` dependency re-loads the user on every request.
    `some_user` must already exist in the same `db_engine`/`db_session` this `client` uses.
    """

    def _set(user: User):
        user_id = user.id  # capture the plain int now, before any session-expiry concerns

        def _override(db: Session = Depends(get_db)) -> User:
            fresh = db.get(User, user_id)
            if fresh is None:
                raise RuntimeError(f"client_as: no User with id={user_id} in this test's database.")
            return fresh

        app.dependency_overrides[get_current_user] = _override
        return client

    return _set


@pytest.fixture()
def unauthenticated_client(client):
    """The same TestClient, but with the default admin auth override removed — requests go
    through real bearer-token verification, so a request with no (or an invalid) token
    correctly gets a real 401, letting `test_auth.py` exercise the actual dependency.
    """
    app.dependency_overrides.pop(get_current_user, None)
    yield client
