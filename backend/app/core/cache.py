"""A small JSON cache in Redis for answers from outside services (the company register, Wikidata,
industry classification). If Redis is down, nothing is cached and the caller just does the work."""

import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

log = logging.getLogger("cache")
_redis: Redis | None = None


def _client() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2)
    return _redis


async def close() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def get_json(key: str) -> Any | None:
    try:
        raw = await _client().get(f"cache:{key}")
    except Exception:  # noqa: BLE001 - see the module docstring
        log.warning("cache unavailable; reading %s uncached", key.split(":", 1)[0])
        return None
    return json.loads(raw) if raw is not None else None


async def set_json(key: str, value: Any, ttl_seconds: int) -> None:
    try:
        await _client().set(f"cache:{key}", json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
    except Exception:  # noqa: BLE001
        pass
