"""Small fixed-window rate limits in Redis, for the endpoints that are open to anyone
(login, signup). If Redis is down the limit is skipped and the request goes ahead: being
unable to sign in at all would be worse than a short gap in throttling."""

import logging

from fastapi import HTTPException, Request
from redis.asyncio import Redis

from app.core.config import get_settings

log = logging.getLogger("ratelimit")
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


def client_ip(request: Request) -> str:
    """The caller's address. Behind the proxy this is the forwarded address, which uvicorn sets
    from X-Forwarded-For when started with --proxy-headers and a trusted --forwarded-allow-ips."""
    return request.client.host if request.client else "unknown"


async def count(key: str) -> int:
    """How many hits the key has in its current window (0 if Redis can't be reached)."""
    try:
        return int(await _client().get(f"rl:{key}") or 0)
    except Exception:  # noqa: BLE001 - see the module docstring
        log.warning("rate limit store unavailable; not limiting %s", key.split(":", 1)[0])
        return 0


async def hit(key: str, window_seconds: int) -> int:
    """Count one hit; the window starts at the first hit. Returns the count in the window."""
    try:
        r = _client()
        n = await r.incr(f"rl:{key}")
        if n == 1:
            await r.expire(f"rl:{key}", window_seconds)
        return int(n)
    except Exception:  # noqa: BLE001
        log.warning("rate limit store unavailable; not limiting %s", key.split(":", 1)[0])
        return 0


async def clear(key: str) -> None:
    try:
        await _client().delete(f"rl:{key}")
    except Exception:  # noqa: BLE001
        pass


def too_many(message: str = "Too many attempts. Wait a few minutes and try again.") -> HTTPException:
    return HTTPException(429, message)
