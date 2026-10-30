from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import Role


class TokenData(BaseModel):
    id: Optional[int] = None


class UserCreate(BaseModel):
    """Public data accepted when a user registers."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    role: Role


class UserOut(BaseModel):
    """Safe representation of a user returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    phone: Optional[str]
    role: Role
    is_active: bool
    created_at: Optional[datetime]
