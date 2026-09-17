from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import validate_password_strength
from app.models.enums import UserRole
from app.schemas.user import UserRead


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class DemoLoginRequest(BaseModel):
    """Which demo persona to log in as — only meaningful (and only reachable) when
    `settings.DEMO_MODE` is true. Defaults to Admin so a demo shows every feature unblocked.
    """

    role: UserRole = UserRole.ADMIN


class DemoModeStatus(BaseModel):
    enabled: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserRead


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=72)

    @field_validator("new_password")
    @classmethod
    def _check_password_strength(cls, value: str) -> str:
        validate_password_strength(value)
        return value
