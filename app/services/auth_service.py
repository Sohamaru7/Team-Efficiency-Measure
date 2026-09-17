from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.models.enums import UserRole
from app.models.revoked_token import RevokedToken
from app.models.user import User

# Fixed, well-known demo accounts (app.core.config.settings.DEMO_MODE) — get-or-created lazily
# by ensure_demo_user, never given a usable password (hashed_password stays None), so the only
# way into one of these accounts is the demo-login endpoint itself, and only while DEMO_MODE is
# on. Manager/Employee share a department so a demo can also show off team-scoped RBAC views.
DEMO_ACCOUNTS: dict[UserRole, dict[str, str | None]] = {
    UserRole.ADMIN: {"name": "Demo Admin", "email": "demo-admin@example.com", "department": None},
    UserRole.MANAGER: {"name": "Demo Manager", "email": "demo-manager@example.com", "department": "Demo Team"},
    UserRole.EMPLOYEE: {"name": "Demo Employee", "email": "demo-employee@example.com", "department": "Demo Team"},
}


def ensure_demo_user(db: Session, role: UserRole) -> User:
    """Get-or-create one of the fixed demo accounts. Only ever called from the demo-login
    route, which itself only runs when `settings.DEMO_MODE` is true — see that route's
    docstring for the full guarantee this relies on.
    """
    info = DEMO_ACCOUNTS[role]
    stmt = select(User).where(func.lower(User.email) == info["email"])
    user = db.scalars(stmt).first()
    if user is not None:
        return user
    user = User(name=info["name"], email=info["email"], role=role, department=info["department"], active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Returns the user only if the email exists, the account is active, and the password
    matches. Deliberately returns `None` (never a distinguishing error) for every failure mode
    — unknown email, inactive account, wrong password, or no password ever set — so a login
    endpoint can give one generic "incorrect email or password" response and not leak which
    part was wrong (avoids user enumeration).
    """
    normalized_email = email.strip().lower()
    stmt = select(User).where(func.lower(User.email) == normalized_email)
    user = db.scalars(stmt).first()
    if user is None or not user.active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def is_token_revoked(db: Session, jti: str) -> bool:
    stmt = select(RevokedToken).where(RevokedToken.jti == jti)
    return db.scalars(stmt).first() is not None


def revoke_token(db: Session, jti: str, expires_at: datetime) -> None:
    if is_token_revoked(db, jti):
        return
    db.add(RevokedToken(jti=jti, expires_at=expires_at))
    db.commit()


def set_password(db: Session, user: User, new_hashed_password: str) -> User:
    user.hashed_password = new_hashed_password
    db.commit()
    db.refresh(user)
    return user
