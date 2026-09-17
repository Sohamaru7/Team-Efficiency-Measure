from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import validate_password_strength
from app.models.enums import UserRole


class UserBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    role: UserRole = UserRole.EMPLOYEE
    department: Optional[str] = Field(default=None, max_length=100)
    active: bool = True


class UserCreate(UserBase):
    password: str = Field(min_length=1, max_length=72, exclude=True)

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, value: str) -> str:
        validate_password_strength(value)
        return value


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    department: Optional[str] = Field(default=None, max_length=100)
    active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=1, max_length=72, exclude=True)

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            validate_password_strength(value)
        return value


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
