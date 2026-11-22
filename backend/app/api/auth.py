from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ChangePasswordIn, LoginIn, MeOut, SignupIn, TenantOut, UserOut
from app.core.auth import COOKIE_NAME, ControlDB, CurrentUser, HomeDB, create_token
from app.core.config import get_settings
from app.core.db import TenantUnavailable, session_for, tenant_of
from app.core.security import hash_password, verify_password
from app.models import AppUser, LoginDirectory, Tenant
from app.models.tenancy import EMPLOYEE_RANGES
from app.services import tenants

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, user: AppUser, tenant: Tenant | None) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        create_token(user, tenant.id if tenant else None),
        httponly=True,
        samesite="lax",
        secure=s.environment == "production",
        max_age=s.jwt_expires_minutes * 60,
        path="/",
    )


def _me(user: AppUser, tenant: Tenant | None) -> MeOut:
    return MeOut(
        user=UserOut.model_validate(user),
        tenant=TenantOut.model_validate(tenant) if tenant else None,
    )


async def _sign_in(db: AsyncSession, email: str, password: str) -> AppUser | None:
    user = (await db.execute(select(AppUser).where(func.lower(AppUser.email) == email))).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return user


@router.post("/login", response_model=MeOut)
async def login(body: LoginIn, response: Response, control: ControlDB) -> MeOut:
    """The login directory says which database the email belongs to; the password is checked there."""
    email = body.email.lower()
    entry = await control.get(LoginDirectory, email)
    user = None
    if entry is not None:
        try:
            async with session_for(entry.tenant_id) as db:
                user = await _sign_in(db, email, body.password)
        except TenantUnavailable:
            user = None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    tenant = await control.get(Tenant, entry.tenant_id) if entry.tenant_id else None
    _set_cookie(response, user, tenant)
    return _me(user, tenant)


@router.post("/signup", response_model=MeOut, status_code=201)
async def signup(body: SignupIn, response: Response, control: ControlDB) -> MeOut:
    """Creates the company, its own database and its first admin. Takes a few seconds."""
    if body.employee_count not in EMPLOYEE_RANGES:
        raise HTTPException(422, "Invalid employee count")
    email = body.email.lower()
    taken = HTTPException(409, "An account with this email already exists")
    if await control.get(LoginDirectory, email):
        raise taken
    try:
        tenant, user = await tenants.provision_tenant(
            control, company_name=body.company_name, industry=body.industry, employee_count=body.employee_count,
            email=email, full_name=body.full_name, password_hash=hash_password(body.password))
    except tenants.EmailTaken:
        raise taken from None
    _set_cookie(response, user, tenant)
    return _me(user, tenant)


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser, db: HomeDB, control: ControlDB) -> MeOut:
    tenant_id = tenant_of(db)
    return _me(user, await control.get(Tenant, tenant_id) if tenant_id else None)


@router.post("/change-password", status_code=204)
async def change_password(body: ChangePasswordIn, user: CurrentUser, db: HomeDB) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    await db.commit()
