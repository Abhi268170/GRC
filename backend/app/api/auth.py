import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.company import industry_fields
from app.api.schemas import ChangePasswordIn, LoginIn, MeOut, SignupIn, TenantOut, UserOut
from app.core import ratelimit
from app.core.auth import COOKIE_NAME, ControlDB, CurrentUser, HomeDB, claims_of, create_token
from app.core.config import get_settings
from app.core.db import TenantUnavailable, session_for, tenant_of
from app.core.security import hash_password_async, verify_password_async
from app.models import AppUser, LoginDirectory, Tenant
from app.models.tenancy import EMPLOYEE_RANGES
from app.services import tenants

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, user: AppUser, tenant_id: uuid.UUID | None) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        create_token(user, tenant_id),
        httponly=True,
        samesite="lax",
        secure=s.is_production,
        max_age=s.jwt_expires_minutes * 60,
        path="/",
    )


def _me(user: AppUser, tenant: Tenant | None) -> MeOut:
    return MeOut(
        user=UserOut.model_validate(user),
        tenant=TenantOut.model_validate(tenant) if tenant else None,
    )


async def _sign_in(db: AsyncSession, email: str, password: str) -> AppUser | None:
    user = (await db.execute(select(AppUser).where(AppUser.email == email))).scalar_one_or_none()
    # Always check a hash, even for an unknown account, so the response time is the same.
    ok = await verify_password_async(password, user.password_hash if user else None)
    if user is None or not ok or not user.is_active:
        return None
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return user


@router.post("/login", response_model=MeOut)
async def login(body: LoginIn, request: Request, response: Response, control: ControlDB) -> MeOut:
    """The login directory says which database the email belongs to; the password is checked there.
    Attempts are limited per address and failures per email."""
    s = get_settings()
    email = body.email.lower()
    if await ratelimit.hit(f"login-ip:{ratelimit.client_ip(request)}", s.login_window_seconds) > s.login_max_attempts_per_ip:
        raise ratelimit.too_many()
    if await ratelimit.count(f"login-fail:{email}") >= s.login_max_failures_per_email:
        raise ratelimit.too_many()

    entry = await control.get(LoginDirectory, email)
    user = None
    if entry is not None:
        try:
            async with session_for(entry.tenant_id) as db:
                user = await _sign_in(db, email, body.password)
        except TenantUnavailable:
            user = None
    else:
        await verify_password_async(body.password, None)
    if user is None:
        await ratelimit.hit(f"login-fail:{email}", s.login_window_seconds)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    await ratelimit.clear(f"login-fail:{email}")
    tenant = await control.get(Tenant, entry.tenant_id) if entry.tenant_id else None
    _set_cookie(response, user, entry.tenant_id)
    return _me(user, tenant)


@router.post("/signup", response_model=MeOut, status_code=201)
async def signup(body: SignupIn, request: Request, response: Response, control: ControlDB) -> MeOut:
    """Creates the company, its own database and its first admin. Every signup creates a database,
    so it is limited per address and in total."""
    s = get_settings()
    if not s.signup_enabled:
        raise HTTPException(403, "Sign-up is closed at the moment. Contact us to get a workspace.")
    if body.employee_count not in EMPLOYEE_RANGES:
        raise HTTPException(422, "Invalid employee count")
    industry, profile = body.industry, body.details.stored()
    if body.noga_code:
        industry, code_fields = industry_fields(body.noga_code)
        profile |= code_fields
    if not industry:
        raise HTTPException(422, "Choose an industry")
    email = body.email.lower()
    taken = HTTPException(409, "An account with this email already exists")
    if await control.get(LoginDirectory, email):
        raise taken
    if await ratelimit.hit(f"signup-ip:{ratelimit.client_ip(request)}", s.signup_window_seconds) > s.signup_max_per_ip:
        raise ratelimit.too_many("Too many workspaces were created from this address. Try again later.")
    if await ratelimit.hit("signup-total", s.signup_window_seconds) > s.signup_max_total:
        raise ratelimit.too_many("Sign-up is busy right now. Try again in a little while.")
    try:
        tenant, user = await tenants.provision_tenant(
            control, company_name=body.company_name, industry=industry, employee_count=body.employee_count,
            profile=profile, email=email, full_name=body.full_name,
            password_hash=await hash_password_async(body.password))
    except tenants.EmailTaken:
        raise taken from None
    _set_cookie(response, user, tenant.id)
    return _me(user, tenant)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    """Ends this session and every other session of the user (the token version goes up)."""
    response.delete_cookie(COOKIE_NAME, path="/")
    claims = claims_of(request)
    if not claims:
        return
    try:
        async with session_for(uuid.UUID(claims["tid"]) if claims.get("tid") else None) as db:
            user = await db.get(AppUser, uuid.UUID(claims["sub"]))
            if user is not None and claims.get("ver", 0) == user.token_version:
                user.token_version += 1
                await db.commit()
    except (TenantUnavailable, ValueError, KeyError):
        pass


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser, db: HomeDB, control: ControlDB) -> MeOut:
    tenant_id = tenant_of(db)
    return _me(user, await control.get(Tenant, tenant_id) if tenant_id else None)


@router.post("/change-password", status_code=204)
async def change_password(body: ChangePasswordIn, response: Response, user: CurrentUser, db: HomeDB) -> None:
    if not await verify_password_async(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(400, "Choose a password that is different from the current one")
    user.password_hash = await hash_password_async(body.new_password)
    user.must_change_password = False
    user.token_version += 1  # signs out every other session
    await db.commit()
    _set_cookie(response, user, tenant_of(db))  # this session continues with a new token
