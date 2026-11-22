"""Enqueue background jobs (arq). Every job has a row in the `job` table for UI status.

The job row lives in the database of whoever owns the work (a company database, or the
control database for platform work), so the worker is told which database to open."""

import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import tenant_of
from app.models import Job

_pool: ArqRedis | None = None


async def pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def enqueue(db: AsyncSession, *, type: str, ref_type: str, ref_id: uuid.UUID, payload: dict | None = None) -> Job:
    """Create the job row, commit, then enqueue (so the worker always finds the row)."""
    job = Job(type=type, ref_type=ref_type, ref_id=ref_id, payload=payload or {})
    db.add(job)
    await db.commit()
    tenant_id = tenant_of(db)
    await (await pool()).enqueue_job(type, str(job.id), str(tenant_id) if tenant_id else None, _job_id=str(job.id))
    return job


async def enqueue_task(name: str, *args: object) -> None:
    """Enqueue background work that has no job row (nothing in the UI waits for it)."""
    await (await pool()).enqueue_job(name, *args)
