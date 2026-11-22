"""Tenant user management (Tenant Admin). Users live in the company database; the login
directory in the control database says which company an email belongs to."""

import secrets
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.schemas import UserOut
from app.core.auth import ControlDB, TenantAdmin, TenantDB, TenantMember
from app.core.db import tenant_of
from app.core.security import hash_password
from app.models import AppUser, LoginDirectory, OrganisationalRole
from app.services import snapshot

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    organisational_role_id: uuid.UUID | None = None
    is_admin: bool = False


class UserCreated(BaseModel):
    user: UserOut
    temporary_password: str


class UserEdit(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    organisational_role_id: uuid.UUID | None = None
    is_admin: bool = False
    is_active: bool = True


async def _check_role(control: ControlDB, db: TenantDB, organisational_role_id: uuid.UUID | None) -> None:
    if organisational_role_id:
        role = await control.get(OrganisationalRole, organisational_role_id)
        if role is None or not role.is_active:
            raise HTTPException(422, "Unknown role")
        # Make sure this company's copy of the roles has it (it may have been added a moment ago).
        await snapshot.sync_master_data(control, db)


@router.get("", response_model=list[UserOut])
async def list_users(db: TenantDB, me: TenantMember) -> list[AppUser]:
    return list((await db.execute(
        select(AppUser).order_by(AppUser.full_name))).scalars())


@router.post("", response_model=UserCreated, status_code=201)
async def create_user(body: UserCreate, db: TenantDB, control: ControlDB, me: TenantAdmin) -> UserCreated:
    email = body.email.lower()
    taken = HTTPException(409, "An account with this email already exists")
    if await control.get(LoginDirectory, email) or (
            await db.execute(select(AppUser.id).where(func.lower(AppUser.email) == email))).first():
        raise taken
    await _check_role(control, db, body.organisational_role_id)
    temp = secrets.token_urlsafe(9)
    user = AppUser(email=email, full_name=body.full_name,
                   password_hash=hash_password(temp), organisational_role_id=body.organisational_role_id,
                   platform_role="tenant_admin" if body.is_admin else "tenant_user", must_change_password=True)
    # Two databases, so no single transaction: reserve the email in the directory first,
    # and give it back if the user can't be saved.
    control.add(LoginDirectory(email=email, tenant_id=tenant_of(db)))
    try:
        await control.commit()
    except IntegrityError:
        raise taken from None
    try:
        db.add(user)
        await db.commit()
    except BaseException:
        await control.execute(delete(LoginDirectory).where(LoginDirectory.email == email))
        await control.commit()
        raise
    return UserCreated(user=UserOut.model_validate(user), temporary_password=temp)


@router.put("/{user_id}", response_model=UserOut)
async def edit_user(user_id: uuid.UUID, body: UserEdit, db: TenantDB, control: ControlDB, me: TenantAdmin) -> AppUser:
    user = await db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == me.id and (not body.is_admin or not body.is_active):
        raise HTTPException(409, "You can't remove your own admin access or deactivate yourself")
    await _check_role(control, db, body.organisational_role_id)
    user.full_name, user.organisational_role_id, user.is_active = body.full_name, body.organisational_role_id, body.is_active
    user.platform_role = "tenant_admin" if body.is_admin else "tenant_user"
    await db.commit()
    return user


@router.post("/{user_id}/reset-password", response_model=UserCreated)
async def reset_password(user_id: uuid.UUID, db: TenantDB, me: TenantAdmin) -> UserCreated:
    user = await db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    temp = secrets.token_urlsafe(9)
    user.password_hash, user.must_change_password = hash_password(temp), True
    await db.commit()
    return UserCreated(user=UserOut.model_validate(user), temporary_password=temp)
