"""Enqueue background jobs (arq). Every job has a row in the `job` table for UI status.

The job row lives in the database of whoever owns the work (a company database, or the
control database for platform work), so the worker is told which database to open."""

import logging
import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import tenant_of
from app.models import Job

log = logging.getLogger("queue")
_pool: ArqRedis | None = None


async def pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue(db: AsyncSession, *, type: str, ref_type: str, ref_id: uuid.UUID, payload: dict | None = None) -> Job:
    """Create the job row, commit, then enqueue (so the worker always finds the row)."""
    job = Job(type=type, ref_type=ref_type, ref_id=ref_id, payload=payload or {})
    db.add(job)
    await db.commit()
    tenant_id = tenant_of(db)
    try:
        await (await pool()).enqueue_job(type, str(job.id), str(tenant_id) if tenant_id else None, _job_id=str(job.id))
    except Exception:
        # The queue can't be reached. Settle the job now, or what it was meant to work on would wait forever.
        from app.services import jobs

        log.exception("could not queue job %s (%s)", job.id, type)
        await jobs.fail(db, job, "The background queue isn't available right now. Please try again in a moment.")
        await db.commit()
        raise HTTPException(503, "The background queue isn't available right now. Please try again in a moment.") from None
    return job


async def enqueue_task(name: str, *args: object, job_id: str | None = None) -> None:
    """Enqueue background work that has no job row (nothing in the UI waits for it). With a
    `job_id`, a second request is dropped while one with the same id is still waiting or running.
    Never raises: the caller's own work is already saved, and these tasks are also run at other times."""
    try:
        await (await pool()).enqueue_job(name, *args, _job_id=job_id)
    except Exception:  # noqa: BLE001
        log.exception("could not queue task %s", name)
