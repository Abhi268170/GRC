import asyncio

from fastapi import APIRouter, Response
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import control_engine
from app.core.storage import bucket_ok

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict:
    return {"status": "ok"}


@router.get("/health")
async def health(response: Response) -> dict:
    checks: dict[str, str] = {}

    try:
        async with control_engine.connect() as conn:
            await conn.execute(text("select 1"))
        checks["database"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["database"] = f"error: {e.__class__.__name__}"

    try:
        redis = Redis.from_url(get_settings().redis_url)
        await redis.ping()
        await redis.aclose()
        checks["redis"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["redis"] = f"error: {e.__class__.__name__}"

    checks["storage"] = "ok" if await asyncio.to_thread(bucket_ok) else "error"

    healthy = all(v == "ok" for v in checks.values())
    response.status_code = 200 if healthy else 503
    return {"status": "ok" if healthy else "degraded", "checks": checks}
