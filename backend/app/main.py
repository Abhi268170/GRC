import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import (
    assessments,
    auth,
    company,
    frameworks,
    health,
    library,
    library_import,
    master_data,
    platform,
    registers,
    runs,
    users,
)
from app.core import cache, logs, queue, ratelimit
from app.core.config import get_settings
from app.core.db import TenantUnavailable, dispose_all
from app.services import ai, company_lookup

log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logs.setup(settings.log_level)
    for warning in settings.unsafe_settings():
        log.warning("unsafe setting: %s", warning)
    yield
    # Close what holds connections: the AI service client, the job queue, every database pool.
    await ai.close()
    await queue.close()
    await ratelimit.close()
    await cache.close()
    await company_lookup.close()
    await dispose_all()


# Served behind a proxy at /api (uvicorn --root-path /api). The interactive docs are for development only.
_docs = not get_settings().is_production
app = FastAPI(title="TrustUp API", version="0.1.0", lifespan=lifespan, docs_url="/docs" if _docs else None,
              redoc_url=None, openapi_url="/openapi.json" if _docs else None)
for module in (health, auth, company, library, library_import, frameworks, assessments, master_data, users, platform, runs, registers):
    app.include_router(module.router)


class RequestId:
    """Gives every request an id (the caller's `X-Request-ID`, or a new one), puts it on log lines
    and on the response, and passes it to the AI service. Plain ASGI, so streamed responses pass
    through untouched."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        given = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")[:64]
        rid = given if given.replace("-", "").isalnum() else uuid.uuid4().hex[:16]
        logs.request_id.set(rid)

        async def send_with_id(message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"x-request-id", rid.encode()))
            await send(message)

        await self.app(scope, receive, send_with_id)


class BodyLimit:
    """Refuses request bodies over the limit (settings.max_request_bytes): at once when the client
    declares the size, otherwise as soon as the bytes received pass it."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await self._refuse(send)
            return
        received, too_large, started = 0, False, False

        async def limited_receive():
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    return {"type": "http.disconnect"}  # the handler stops reading
            return message

        async def guarded_send(message) -> None:
            nonlocal started
            if too_large and not started:
                return  # the handler's own error response is replaced by the 413 below
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not too_large:
                raise
        if too_large and not started:
            await self._refuse(send)

    async def _refuse(self, send) -> None:
        body = b'{"detail":"The request is too large."}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


app.add_middleware(BodyLimit, max_bytes=get_settings().max_request_bytes)
app.add_middleware(RequestId)


@app.exception_handler(ai.AIError)
async def ai_failed(request: Request, exc: ai.AIError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(TenantUnavailable)
async def tenant_unavailable(request: Request, exc: TenantUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "This workspace isn't available right now."})


@app.exception_handler(Exception)
async def unexpected(request: Request, exc: Exception) -> JSONResponse:
    """Anything unhandled: log it with the request id, and tell the client nothing about the internals."""
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={
        "detail": "Something went wrong on our side. Please try again.", "request_id": logs.request_id.get()})
