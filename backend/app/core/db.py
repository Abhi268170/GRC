"""Database sessions.

There is one control database (tenant registry, login directory, super admin, library,
master data) and one database per company (users, runs and everything under them).
See TENANT_DATABASE_PLAN.md.

Every session carries the tenant it belongs to in `session.info["tenant_id"]`
(None for the control database); read it with `tenant_of(session)`."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import URL, make_url, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

control_engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
ControlSession = async_sessionmaker(control_engine, expire_on_commit=False, info={"tenant_id": None})

# Company engines are created on first use and kept. Pools are small because every
# company database holds its own connections.
_tenant_engines: dict[uuid.UUID, AsyncEngine] = {}
_tenant_sessions: dict[uuid.UUID, async_sessionmaker[AsyncSession]] = {}


class TenantUnavailable(Exception):
    """The company doesn't exist or its database isn't ready."""


def database_name_for(tenant_id: uuid.UUID) -> str:
    return f"{make_url(get_settings().database_url).database}_t_{tenant_id.hex}"


def url_for_database(name: str) -> URL:
    return make_url(get_settings().database_url).set(database=name)


def tenant_of(db: AsyncSession) -> uuid.UUID | None:
    """The tenant whose database this session is connected to (None = control database)."""
    return db.info.get("tenant_id")


def open_tenant_database(tenant_id: uuid.UUID, db_name: str) -> async_sessionmaker[AsyncSession]:
    """Session factory for a company database, cached per tenant."""
    maker = _tenant_sessions.get(tenant_id)
    if maker is None:
        engine = create_async_engine(url_for_database(db_name), pool_pre_ping=True, pool_size=2, max_overflow=3)
        _tenant_engines[tenant_id] = engine
        maker = async_sessionmaker(engine, expire_on_commit=False, info={"tenant_id": tenant_id})
        _tenant_sessions[tenant_id] = maker
    return maker


async def forget_tenant(tenant_id: uuid.UUID) -> None:
    """Close and drop the cached connections of a company database."""
    _tenant_sessions.pop(tenant_id, None)
    engine = _tenant_engines.pop(tenant_id, None)
    if engine is not None:
        await engine.dispose()


async def _tenant_maker(tenant_id: uuid.UUID) -> async_sessionmaker[AsyncSession]:
    maker = _tenant_sessions.get(tenant_id)
    if maker is None:
        from app.models import Tenant

        async with ControlSession() as control:
            row = (await control.execute(select(Tenant.db_name, Tenant.status).where(Tenant.id == tenant_id))).first()
        if row is None or row.status != "active":
            raise TenantUnavailable(str(tenant_id))
        maker = open_tenant_database(tenant_id, row.db_name)
    return maker


@asynccontextmanager
async def session_for(tenant_id: uuid.UUID | None) -> AsyncIterator[AsyncSession]:
    """A session on the control database (tenant_id None) or on a company database."""
    maker = ControlSession if tenant_id is None else await _tenant_maker(tenant_id)
    async with maker() as session:
        yield session


async def dispose_all() -> None:
    for tenant_id in list(_tenant_engines):
        await forget_tenant(tenant_id)
    await control_engine.dispose()
