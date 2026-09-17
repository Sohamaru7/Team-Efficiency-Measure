from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.database.session import get_db
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, DemoLoginRequest, DemoModeStatus, LoginRequest, TokenResponse
from app.schemas.user import UserRead
from app.services import auth_service
from app.services.auth_service import authenticate_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

_bearer_scheme = HTTPBearer(auto_error=False)


@router.get("/demo-mode", response_model=DemoModeStatus)
def get_demo_mode_status() -> DemoModeStatus:
    """Public, unauthenticated — lets the login page decide whether to offer a one-click demo
    entry. Reflects `settings.DEMO_MODE` directly; carries no other information.
    """
    return DemoModeStatus(enabled=settings.DEMO_MODE)


@router.post("/demo-login", response_model=TokenResponse)
def demo_login(data: DemoLoginRequest = DemoLoginRequest(), db: Session = Depends(get_db)) -> TokenResponse:
    """Issue a real, fully valid access token for a fixed demo account — **no credentials
    required**. Only reachable when `settings.DEMO_MODE` is true; otherwise this behaves as if
    it doesn't exist (404), the same way a disabled feature should, rather than returning a
    403 that confirms the route is real. See `app.services.auth_service.ensure_demo_user` and
    `DEMO_ACCOUNTS` for the fixed demo personas (role defaults to Admin, so a demo shows every
    feature unblocked — request `{"role": "manager"}` or `{"role": "employee"}` to instead log
    in as one of the team-scoped demo personas). Every other part of the auth/authz system
    (RBAC, rate limiting, token expiry/revocation) is completely unaffected — this issues a
    perfectly ordinary token via the exact same `create_access_token` the real login uses.
    """
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    user = auth_service.ensure_demo_user(db, data.role)
    token, _jti, expires_at = create_access_token(user.id, user.role.value)
    return TokenResponse(access_token=token, expires_at=expires_at, user=UserRead.model_validate(user))


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, data: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Exchange an email + password for a short-lived JWT access token. Always returns the
    same generic error for a wrong email *or* wrong password (see `authenticate_user`) — this
    endpoint never confirms whether a given email is registered. Rate-limited (10/minute per
    client IP, stricter than the app-wide default) specifically to slow down password guessing.
    """
    user = authenticate_user(db, data.email, data.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")

    token, _jti, expires_at = create_access_token(user.id, user.role.value)
    return TokenResponse(access_token=token, expires_at=expires_at, user=UserRead.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    current_user: User = Depends(get_current_user),  # ensures the token was valid before we bother revoking it
    db: Session = Depends(get_db),
) -> None:
    """Revokes the presented access token immediately (see `RevokedToken`) — a logged-out token
    is rejected on its very next use, not just eventually once it expires.
    """
    payload = decode_access_token(credentials.credentials)
    expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    auth_service.revoke_token(db, payload["jti"], expires_at)


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    data: ChangePasswordRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    """Self-service password change — requires the *current* password (unlike an admin's
    `PATCH /api/users/{id}` reset), so a hijacked-but-not-yet-expired session alone isn't
    enough to lock the real owner out.
    """
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect.")
    auth_service.set_password(db, current_user, hash_password(data.new_password))
