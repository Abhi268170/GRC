"""Shared API schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    platform_role: str
    organisational_role_id: uuid.UUID | None
    must_change_password: bool
    is_active: bool
    last_login_at: datetime | None


class TenantOut(ORM):
    id: uuid.UUID
    name: str
    industry: str | None
    employee_count: str | None


class MeOut(BaseModel):
    user: UserOut
    tenant: TenantOut | None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class SignupIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    industry: str = Field(min_length=2, max_length=100)
    employee_count: str
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)
