"""Health endpoints (no sign-in needed).

- /health/live: the process answers. For container liveness checks.
- /health/ready (and /health): the database, the queue and file storage answer, each within
  two seconds. For load balancers and deploy checks."""

import asyncio

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core import ratelimit
from app.core.db import control_engine
from app.core.storage import bucket_ok

router = APIRouter(tags=["health"])
CHECK_SECONDS = 2.0


@router.get("/health/live")
async def live() -> dict:
    return {"status": "ok"}


async def _database() -> None:
    async with control_engine.connect() as conn:
        await conn.execute(text("select 1"))


async def _redis() -> None:
    await ratelimit._client().ping()


async def _storage() -> None:
    if not await asyncio.to_thread(bucket_ok):
        raise RuntimeError("bucket not reachable")


async def _check(probe) -> str:
    try:
        await asyncio.wait_for(probe(), CHECK_SECONDS)
        return "ok"
    except Exception as e:  # noqa: BLE001 - report the kind of failure, never its details
        return f"error: {e.__class__.__name__}"


@router.get("/health/ready")
@router.get("/health")
async def ready(response: Response) -> dict:
    database, redis, storage = await asyncio.gather(_check(_database), _check(_redis), _check(_storage))
    checks = {"database": database, "redis": redis, "storage": storage}
    healthy = all(v == "ok" for v in checks.values())
    response.status_code = 200 if healthy else 503
    return {"status": "ok" if healthy else "degraded", "checks": checks}
