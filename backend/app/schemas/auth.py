from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: UserRole
    is_active: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class InvitationPreview(BaseModel):
    """What the activation page shows before asking for a password."""

    email: EmailStr
    expires_at: dt.datetime


class ActivateAccount(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)
