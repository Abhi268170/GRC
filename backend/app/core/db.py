"""Database sessions.

There is one control database (tenant registry, login directory, super admin, library,
master data) and one database per company (users, runs and everything under them).
See TENANT_DATABASE_PLAN.md.

Every session carries the tenant it belongs to in `session.info["tenant_id"]`
(None for the control database); read it with `tenant_of(session)`."""

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import URL, make_url, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

# Connections give up after 10 s connecting and 120 s on one statement, and are replaced every
# 30 minutes, so a stuck query or a dead connection can't hold a pool slot for ever.
ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 1800, "connect_args": {"timeout": 10, "command_timeout": 120}}

control_engine = create_async_engine(get_settings().database_url, **ENGINE_OPTIONS)
ControlSession = async_sessionmaker(control_engine, expire_on_commit=False, info={"tenant_id": None})

# Company engines are created on first use. Every one holds its own connections, so only the most
# recently used are kept (settings.tenant_pool_cache_size); the least recently used one is closed
# when the cache is full, and reopened the next time that company makes a request.
_tenant_engines: OrderedDict[uuid.UUID, AsyncEngine] = OrderedDict()
_tenant_sessions: dict[uuid.UUID, async_sessionmaker[AsyncSession]] = {}
_closing: set[asyncio.Task] = set()


class TenantUnavailable(Exception):
    """The company doesn't exist or its database isn't ready."""


def database_name_for(tenant_id: uuid.UUID) -> str:
    return f"{make_url(get_settings().database_url).database}_t_{tenant_id.hex}"


def url_for_database(name: str) -> URL:
    return make_url(get_settings().database_url).set(database=name)


def tenant_of(db: AsyncSession) -> uuid.UUID | None:
    """The tenant whose database this session is connected to (None = control database)."""
    return db.info.get("tenant_id")


def _close_later(engine: AsyncEngine) -> None:
    """Dispose an evicted engine without making the current request wait. Sessions still using it
    keep their connection; it is closed when they return it."""
    task = asyncio.get_running_loop().create_task(engine.dispose())
    _closing.add(task)
    task.add_done_callback(_closing.discard)


def open_tenant_database(tenant_id: uuid.UUID, db_name: str) -> async_sessionmaker[AsyncSession]:
    """Session factory for a company database, cached per tenant."""
    maker = _tenant_sessions.get(tenant_id)
    if maker is not None:
        _tenant_engines.move_to_end(tenant_id)
        return maker
    s = get_settings()
    engine = create_async_engine(url_for_database(db_name), pool_size=s.tenant_pool_size,
                                 max_overflow=s.tenant_pool_overflow, **ENGINE_OPTIONS)
    _tenant_engines[tenant_id] = engine
    maker = async_sessionmaker(engine, expire_on_commit=False, info={"tenant_id": tenant_id})
    _tenant_sessions[tenant_id] = maker
    while len(_tenant_engines) > max(1, s.tenant_pool_cache_size):
        old_id, old_engine = _tenant_engines.popitem(last=False)
        _tenant_sessions.pop(old_id, None)
        _close_later(old_engine)
    return maker


async def forget_tenant(tenant_id: uuid.UUID) -> None:
    """Close and drop the cached connections of a company database."""
    _tenant_sessions.pop(tenant_id, None)
    engine = _tenant_engines.pop(tenant_id, None)
    if engine is not None:
        await engine.dispose()


async def _tenant_maker(tenant_id: uuid.UUID) -> async_sessionmaker[AsyncSession]:
    maker = _tenant_sessions.get(tenant_id)
    if maker is not None:
        _tenant_engines.move_to_end(tenant_id)
    else:
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
    if _closing:
        await asyncio.gather(*_closing, return_exceptions=True)
    await control_engine.dispose()
