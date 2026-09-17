"""Password hashing and JWT access tokens — the two primitives `app.services.auth_service` and
`app.api.deps` build on. Pure/stateless: no DB access here, so both halves are independently
unit-testable (see `tests/test_security_core.py`).

- Passwords are hashed with bcrypt (via the `bcrypt` package directly, not a passlib wrapper —
  fewer moving parts, actively maintained). A bcrypt hash already embeds its own random salt;
  we never store or handle a plaintext password anywhere past `hash_password`.
- Access tokens are signed JWTs (HS256) carrying `sub` (user id, as a string per the JWT spec),
  `role`, `exp`, and a random `jti` (used for logout — see `app.models.revoked_token`). There
  is no refresh-token flow: a token is valid for `ACCESS_TOKEN_EXPIRE_MINUTES` and then a new
  login is required — a deliberate scope choice (see README Known Limitations), not an
  oversight.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

logger = logging.getLogger(__name__)


def _resolve_secret_key() -> str:
    if settings.JWT_SECRET_KEY:
        return settings.JWT_SECRET_KEY
    logger.warning(
        "JWT_SECRET_KEY is not set in configuration — using a random, process-local secret. "
        "Every issued token will stop working the next time this process restarts. This is "
        "acceptable for local development and tests, but a real deployment must set "
        "JWT_SECRET_KEY explicitly (see .env.example)."
    )
    return secrets.token_urlsafe(64)


# Resolved once per process, not per call — see module docstring.
_SECRET_KEY = _resolve_secret_key()
_ALGORITHM = settings.JWT_ALGORITHM

_BCRYPT_MAX_PASSWORD_BYTES = 72  # bcrypt silently ignores bytes past this — enforce it explicitly


class PasswordTooLongError(ValueError):
    pass


MIN_PASSWORD_LENGTH = 8


def validate_password_strength(password: str) -> None:
    """Minimal, deliberately simple complexity rule (length + at least one letter and one
    digit) — not a full entropy/strength meter (e.g. zxcvbn). Raises `ValueError` so it can be
    called directly from a Pydantic `field_validator` and surface as a normal 422.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if not any(c.isalpha() for c in password):
        raise ValueError("Password must contain at least one letter.")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must contain at least one digit.")


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > _BCRYPT_MAX_PASSWORD_BYTES:
        raise PasswordTooLongError(f"Password must be at most {_BCRYPT_MAX_PASSWORD_BYTES} bytes.")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str | None) -> bool:
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed hash (shouldn't happen for anything this module wrote) — fail closed.
        return False


def create_access_token(user_id: int, role: str) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at) — the jti/expiry are also returned directly so a caller
    never has to re-decode a token it just created (e.g. nothing to do with logout of the
    *current* token, which decodes the incoming token instead — see `decode_access_token`).
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    jti = str(uuid.uuid4())
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": expires_at, "jti": jti}
    token = jwt.encode(payload, _SECRET_KEY, algorithm=_ALGORITHM)
    return token, jti, expires_at


class InvalidTokenError(ValueError):
    pass


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises InvalidTokenError (never a raw jwt/PyJWT exception) for any of: malformed token,
    bad signature, expired token, wrong algorithm — callers don't need to know which.
    """
    try:
        return jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Invalid or expired token") from exc
