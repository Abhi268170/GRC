"""JWT session auth. The token is stored in an httpOnly cookie (same-origin via the
Next.js proxy); a Bearer header is also accepted for API clients.

The token says which company the user belongs to (`tid`), and that decides which database
the request works on: the company's own database, or the control database for the super admin."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import ControlSession, TenantUnavailable, session_for, tenant_of
from app.models import AppUser

COOKIE_NAME = "grc_session"


def create_token(user: AppUser, tenant_id: uuid.UUID | None) -> str:
    s = get_settings()
    payload = {
        "sub": str(user.id),
        "role": user.platform_role,
        "tid": str(tenant_id) if tenant_id else None,
        "ver": user.token_version,
        "exp": datetime.now(UTC) + timedelta(minutes=s.jwt_expires_minutes),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def _token_from_request(request: Request) -> str | None:
    if token := request.cookies.get(COOKIE_NAME):
        return token
    header = request.headers.get("authorization", "")
    return header[7:] if header.lower().startswith("bearer ") else None


def _claims(request: Request) -> dict:
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired") from None


async def get_control_session() -> AsyncIterator[AsyncSession]:
    async with ControlSession() as session:
        yield session


# The control database: library, master data, catalog, tenant registry.
ControlDB = Annotated[AsyncSession, Depends(get_control_session)]


async def get_home_session(request: Request, control: ControlDB) -> AsyncIterator[AsyncSession]:
    """The signed-in user's own database: their company's, or the control database for the super admin."""
    claims = _claims(request)
    request.state.claims = claims
    if not claims.get("tid"):
        yield control
        return
    try:
        home = session_for(uuid.UUID(claims["tid"]))
        session = await home.__aenter__()
    except TenantUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "This workspace isn't available right now. Try again shortly.") from None
    try:
        yield session
    finally:
        await home.__aexit__(None, None, None)


HomeDB = Annotated[AsyncSession, Depends(get_home_session)]


async def current_user(request: Request, db: HomeDB) -> AppUser:
    user = await db.get(AppUser, uuid.UUID(request.state.claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not available")
    if request.state.claims.get("ver", 0) != user.token_version:
        # The password was changed or reset, or the user signed out: older sessions end here.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    # Temporary passwords only allow signing in and setting a new password.
    if user.must_change_password and not request.url.path.rstrip("/").endswith(("/auth/me", "/auth/change-password", "/auth/logout")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Set a new password to continue")
    return user


CurrentUser = Annotated[AppUser, Depends(current_user)]


def claims_of(request: Request) -> dict | None:
    """The session token's claims, or None when there is no valid token. Never raises."""
    try:
        return _claims(request)
    except HTTPException:
        return None


def require(*roles: str):
    async def dep(user: CurrentUser, db: HomeDB) -> AppUser:
        if user.platform_role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        # The super admin exists only in the control database, whatever a company database's rows say.
        if (user.platform_role == "super_admin") != (tenant_of(db) is None):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        return user

    return Depends(dep)


SuperAdmin = Annotated[AppUser, require("super_admin")]
TenantAdmin = Annotated[AppUser, require("tenant_admin")]
TenantMember = Annotated[AppUser, require("tenant_admin", "tenant_user")]


async def get_tenant_session(db: HomeDB) -> AsyncSession:
    if tenant_of(db) is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    return db


# The signed-in user's company database. It is the same session `CurrentUser` was loaded from.
TenantDB = Annotated[AsyncSession, Depends(get_tenant_session)]
