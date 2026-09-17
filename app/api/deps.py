"""FastAPI authentication/authorization dependencies (production-readiness pass). Thin wrappers
over `app.core.security` (token decode) and `app.services.authz` (role/ownership rules) — the
actual rules live in those framework-free modules so they stay unit-testable without spinning
up FastAPI; this module only adapts them to `Depends()`.

`get_current_user` is the single source of truth for "who is making this request": it verifies
the bearer token's signature and expiry, rejects a logged-out (revoked) token, and loads the
real `User` row — every protected route depends on it (directly or via `require_roles`), never
on a client-supplied id (closing exactly the gap every earlier phase's README flagged: "there is
no real authentication... a caller-supplied id is trusted at face value").
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import InvalidTokenError, decode_access_token
from app.database.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.services import auth_service, user_service

_bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise _unauthorized()

    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise _unauthorized() from exc

    jti = payload.get("jti")
    if jti and auth_service.is_token_revoked(db, jti):
        raise _unauthorized()

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _unauthorized() from exc

    user = user_service.get_user(db, user_id)
    if user is None or not user.active:
        raise _unauthorized()
    return user


def require_roles(*roles: UserRole):
    """Returns a Depends-compatible callable that additionally requires the caller's role to be
    one of `roles`. Use directly for route-level (not resource-level) checks — e.g. "only a
    manager or admin may open the Manager AI Assistant at all." For per-resource ownership
    checks (a specific task/user/daily-update), call `app.services.authz` predicates directly
    in the route body instead, since only the handler has the resolved resource to check
    against.
    """

    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to perform this action."
            )
        return current_user

    return _dependency


require_admin = require_roles(UserRole.ADMIN)
require_manager_or_admin = require_roles(UserRole.MANAGER, UserRole.ADMIN)


def forbidden(detail: str = "You do not have permission to access this resource.") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
