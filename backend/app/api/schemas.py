"""Shared API schemas."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


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
    # The company details the user saved (see CompanyDetails) and the industry code (noga_*). May be empty.
    profile: dict = {}


_WEBSITE = re.compile(r"^https?://[^\s/.]+(\.[^\s/.]+)+(/\S*)?$", re.IGNORECASE)


class CompanyDetails(BaseModel):
    """What a company says about itself. At sign-up the fields are filled in from the commercial
    register where it has them; the user can change every one and is the one who saves them."""

    registration_number: str | None = Field(default=None, max_length=50)   # CHE-000.000.000 in Switzerland
    legal_form: str | None = Field(default=None, max_length=100)
    street: str | None = Field(default=None, max_length=200)
    house_number: str | None = Field(default=None, max_length=20)
    zip: str | None = Field(default=None, max_length=20)
    city: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)               # canton, state or province
    country: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=4000)         # what the company does

    @field_validator("*", mode="before")
    @classmethod
    def _tidy(cls, value: object) -> object:
        """Collapse whitespace; an empty field is no value."""
        if isinstance(value, str):
            value = " ".join(value.split())
        return value or None

    @field_validator("website")
    @classmethod
    def _web_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "://" not in value:
            value = "https://" + value
        if not _WEBSITE.match(value):
            raise ValueError("Enter a web address like example.com")
        return value

    def stored(self) -> dict:
        return self.model_dump(exclude_none=True)


class MeOut(BaseModel):
    user: UserOut
    tenant: TenantOut | None


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class SignupIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    # The industry is a NOGA 2025 code (six digits). `industry` as free text is still accepted
    # when no code is given.
    noga_code: str | None = Field(default=None, max_length=6)
    industry: str | None = Field(default=None, min_length=2, max_length=200)
    employee_count: str
    # Address, legal form, website, ...: prefilled from the commercial register in the browser,
    # checked and possibly changed by the visitor.
    details: CompanyDetails = CompanyDetails()
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=10, max_length=200)
