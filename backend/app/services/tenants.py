"""Company databases: creating one, migrating all of them, and work that spans them.
See TENANT_DATABASE_PLAN.md."""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import TypeVar

from alembic.config import Config
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from app.core.db import (
    ControlSession,
    control_engine,
    database_name_for,
    forget_tenant,
    open_tenant_database,
    session_for,
)
from app.models import AppUser, AssessmentRun, AssessmentVersion, LoginDirectory, Notification, Tenant
from app.services import snapshot

log = logging.getLogger("tenants")
T = TypeVar("T")

BACKEND_DIR = Path(__file__).resolve().parents[2]
REGISTRY_REVISION = "b7d2e9f1a3c5"  # control migration that adds tenant.db_name and login_directory
SAFE_NAME = re.compile(r"^[a-z0-9_]+$")


class EmailTaken(Exception):
    pass


# ---------- migrations ----------


def _alembic(tree: str, db_name: str | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"), ini_section="alembic" if tree == "control" else tree)
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic" / tree))
    cfg.attributes["db_name"] = db_name
    cfg.attributes["skip_logging"] = True  # keep the running app's logging as it is
    return cfg


# The Alembic environments start their own event loop, so call these from a plain thread
# (`await asyncio.to_thread(...)`), never directly from async code.
def upgrade_control(revision: str = "head") -> None:
    command.upgrade(_alembic("control"), revision)


def upgrade_tenant_database(db_name: str) -> None:
    command.upgrade(_alembic("tenant", db_name), "head")


# ---------- databases ----------


def _checked(name: str) -> str:
    if not SAFE_NAME.match(name):
        raise ValueError(f"Unexpected database name: {name!r}")
    return name


async def _admin_sql(statement: str) -> None:
    """CREATE/DROP DATABASE can't run inside a transaction."""
    async with control_engine.connect() as conn:
        await (await conn.execution_options(isolation_level="AUTOCOMMIT")).execute(text(statement))


async def create_database(name: str) -> None:
    await _admin_sql(f'CREATE DATABASE "{_checked(name)}"')


async def drop_database(name: str) -> None:
    await _admin_sql(f'DROP DATABASE IF EXISTS "{_checked(name)}" WITH (FORCE)')


async def _database_exists(name: str) -> bool:
    async with control_engine.connect() as conn:
        return bool((await conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name})).first())


# ---------- creating and removing a company ----------


async def provision_tenant(control: AsyncSession, *, company_name: str, industry: str | None, employee_count: str | None,
                           email: str, full_name: str, password_hash: str) -> tuple[Tenant, AppUser]:
    """Create a company: registry row, its own database, the master data mirror and its first admin.
    If any step fails, everything created so far is removed again."""
    tenant = Tenant(id=uuid.uuid4(), name=company_name, industry=industry, employee_count=employee_count, status="provisioning")
    tenant.db_name = database_name_for(tenant.id)
    control.add(tenant)
    await control.flush()
    control.add(LoginDirectory(email=email, tenant_id=tenant.id))  # reserves the email
    try:
        await control.commit()
    except IntegrityError:
        await control.rollback()
        raise EmailTaken(email) from None

    tenant_id, db_name = tenant.id, tenant.db_name
    try:
        await create_database(db_name)
        await asyncio.to_thread(upgrade_tenant_database, db_name)
        async with open_tenant_database(tenant_id, db_name)() as db:
            await snapshot.sync_master_data(control, db)
            user = AppUser(email=email, password_hash=password_hash, full_name=full_name,
                           platform_role="tenant_admin", last_login_at=func.now())
            db.add(user)
            await db.commit()
            await db.refresh(user)
        tenant.status = "active"
        await control.commit()
    except BaseException:
        log.exception("could not set up company %s; removing what was created", tenant_id)
        await control.rollback()
        await remove_tenant(control, tenant_id, db_name)
        raise
    return tenant, user


async def remove_tenant(control: AsyncSession, tenant_id: uuid.UUID, db_name: str) -> None:
    """Drop a company's database and its registry and login directory rows."""
    await forget_tenant(tenant_id)
    await drop_database(db_name)
    # The login directory rows go with the registry row (ON DELETE CASCADE).
    await control.execute(delete(Tenant).where(Tenant.id == tenant_id))
    await control.commit()


async def remove_unfinished(control: AsyncSession) -> int:
    """Companies left half set up by a signup that was interrupted. A signup takes seconds, so only
    rows older than 15 minutes are removed: one still running on another replica is left alone."""
    unfinished = (await control.execute(select(Tenant.id, Tenant.db_name).where(
        Tenant.status == "provisioning", Tenant.created_at < func.now() - timedelta(minutes=15)))).all()
    for tenant_id, db_name in unfinished:
        await remove_tenant(control, tenant_id, db_name)
    return len(unfinished)


# ---------- work that spans companies ----------


async def active_tenants(control: AsyncSession) -> list[Tenant]:
    return list((await control.execute(select(Tenant).where(Tenant.status == "active").order_by(Tenant.created_at))).scalars())


async def for_each_tenant(work: Callable[[AsyncSession], Awaitable[T]]) -> dict[uuid.UUID, T]:
    """Run `work` on every active company database, one after the other, and commit each.
    A failing database is logged and left out of the result; the others still run."""
    async with ControlSession() as control:
        tenants = await active_tenants(control)
    results: dict[uuid.UUID, T] = {}
    for tenant in tenants:
        try:
            async with session_for(tenant.id) as db:
                results[tenant.id] = await work(db)
                await db.commit()
        except Exception:  # noqa: BLE001 - one company must not stop the rest
            log.exception("work on company %s (%s) failed", tenant.id, tenant.db_name)
    return results


async def sync_master_data_everywhere() -> int:
    async with ControlSession() as control:
        return len(await for_each_tenant(lambda db: snapshot.sync_master_data(control, db)))


async def deprecate_everywhere(version_id: uuid.UUID, payload: dict) -> int:
    """Returns the number of notifications created across all companies."""
    return sum((await for_each_tenant(lambda db: snapshot.deprecate_assessment_version(db, version_id, payload))).values())


_run_counts: tuple[float, dict[uuid.UUID, int]] | None = None
RUN_COUNTS_SECONDS = 120


async def run_counts() -> dict[uuid.UUID, int]:
    """Runs per assessment (all versions), across all companies. It reads every company database,
    so the result is kept for two minutes."""
    global _run_counts
    if _run_counts and time.monotonic() - _run_counts[0] < RUN_COUNTS_SECONDS:
        return _run_counts[1]
    async def count(db: AsyncSession) -> list[tuple[uuid.UUID, int]]:
        return [(aid, n) for aid, n in await db.execute(
            select(AssessmentVersion.assessment_id, func.count())
            .join(AssessmentRun, AssessmentRun.assessment_version_id == AssessmentVersion.id)
            .group_by(AssessmentVersion.assessment_id))]

    totals: dict[uuid.UUID, int] = {}
    for rows in (await for_each_tenant(count)).values():
        for assessment_id, n in rows:
            totals[assessment_id] = totals.get(assessment_id, 0) + n
    _run_counts = (time.monotonic(), totals)
    return totals


# ---------- `python -m app.tenants migrate` ----------


async def _split_legacy_tenants() -> int:
    """One-off move from the old layout (every company in one database, rows marked with tenant_id):
    give each company its own database and copy its users and notifications there. The control
    migration that follows deletes the originals. Safe to run again if interrupted."""
    async with control_engine.connect() as conn:
        tenant_ids = (await conn.execute(text("SELECT id FROM tenant WHERE db_name IS NULL ORDER BY created_at"))).scalars().all()
    for tenant_id in tenant_ids:
        db_name = database_name_for(tenant_id)
        if not await _database_exists(db_name):
            await create_database(db_name)
        await asyncio.to_thread(upgrade_tenant_database, db_name)
        async with ControlSession() as control, open_tenant_database(tenant_id, db_name)() as db:
            await snapshot.sync_master_data(control, db)
            for model, columns in (
                (AppUser, ("id", "email", "password_hash", "full_name", "platform_role", "organisational_role_id",
                           "must_change_password", "is_active", "last_login_at", "created_at", "updated_at")),
                (Notification, ("id", "user_id", "type", "payload", "read_at", "created_at")),
            ):
                table = model.__table__
                rows = [dict(r) for r in (await control.execute(
                    select(*(table.c[name] for name in columns)).where(text("tenant_id = :t")), {"t": tenant_id})).mappings()]
                if rows:
                    await db.execute(insert(table).values(rows).on_conflict_do_nothing())
                log.info("company %s: moved %d %s row(s) to %s", tenant_id, len(rows), table.name, db_name)
            await db.commit()
            await control.execute(text("UPDATE tenant SET db_name = :n, status = 'active' WHERE id = :t"),
                                  {"n": db_name, "t": tenant_id})
            await control.commit()
    return len(tenant_ids)


async def _has_legacy_layout() -> bool:
    async with control_engine.connect() as conn:
        return bool((await conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
            "AND table_name = 'app_user' AND column_name = 'tenant_id'"))).first())


MIGRATION_LOCK = 4242_0001  # advisory lock on the control database: one migration run at a time


async def migrate_all() -> list[str]:
    """Upgrade the control database, then every company database. Returns the companies that failed.

    A company whose database can't be upgraded is marked `migration_failed` and taken offline; the
    platform still starts for everyone else, and the next run tries that company again. Only one
    run happens at a time, across replicas."""
    async with control_engine.connect() as lock:
        await lock.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK})
        try:
            return await _migrate_all()
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK})


async def _migrate_all() -> list[str]:
    if await _has_legacy_layout():
        await asyncio.to_thread(upgrade_control, REGISTRY_REVISION)
        moved = await _split_legacy_tenants()
        log.info("moved %d company(ies) to their own databases", moved)
    await asyncio.to_thread(upgrade_control)

    async with ControlSession() as control:
        removed = await remove_unfinished(control)
        if removed:
            log.info("removed %d half set up company(ies)", removed)
        companies = (await control.execute(select(Tenant).where(Tenant.status.in_(("active", "migration_failed")))
                                           .order_by(Tenant.created_at))).scalars().all()
        failed = []
        for tenant in companies:
            try:
                await asyncio.to_thread(upgrade_tenant_database, tenant.db_name)
                tenant.status = "active"
            except Exception:  # noqa: BLE001 - report every failure, don't stop at the first
                log.exception("could not migrate company %s (%s); it is offline until this is fixed", tenant.id, tenant.db_name)
                tenant.status = "migration_failed"
                failed.append(f"{tenant.id} ({tenant.db_name})")
            await control.commit()
    log.info("migrated the control database and %d of %d company database(s)", len(companies) - len(failed), len(companies))
    return failed
