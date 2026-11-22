"""Client of the AI service. Every AI feature goes through here.

The AI service owns the prompts, output schemas and model calls and has no database. This
module sends it structured data (the models in `ai_contracts`), gets validated results back,
and records what each call used in the right database: the backend owns the per-run AI budget."""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from ai_contracts import (
    ErrorEvent,
    ErrorResponse,
    FinalEvent,
    GuideStepIn,
    GuideSystemIn,
    GuideSystemOut,
    TaskResponse,
    TextEvent,
    ToolStartEvent,
    Usage,
)
from pydantic import BaseModel, ValidationError

from app.core import logs
from app.core.config import get_settings

log = logging.getLogger("ai")
T = TypeVar("T", bound=BaseModel)

UNREACHABLE = "Could not reach the AI service"


class AIError(RuntimeError):
    """An AI call failed. The message is safe to show to a user."""


@dataclass
class UsageTag:
    feature: str
    tenant_id: uuid.UUID | None = None  # whose database the usage is recorded in (None = control)
    run_id: uuid.UUID | None = None


# ---------- usage ----------


async def record_usage(tag: UsageTag | None, usage: Usage | None) -> None:
    """Log one call in its own transaction, so it counts even if the caller's work rolls back."""
    if tag is None or usage is None:
        return
    from app.core.db import session_for
    from app.models import AiUsage

    try:
        async with session_for(tag.tenant_id) as db:
            db.add(AiUsage(
                run_id=tag.run_id, feature=tag.feature, model=usage.model,
                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens, cache_write_tokens=usage.cache_write_tokens,
                cost_usd=usage.cost_usd,
            ))
            await db.commit()
    except Exception:  # noqa: BLE001 - metering must never break the feature itself
        log.exception("could not record AI usage")


async def run_spend(db: Any, run_id: uuid.UUID) -> float:
    from sqlalchemy import func, select

    from app.models import AiUsage

    return float((await db.execute(select(func.coalesce(func.sum(AiUsage.cost_usd), 0)).where(AiUsage.run_id == run_id))).scalar())


# ---------- HTTP ----------

_http: httpx.AsyncClient | None = None


def http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        s = get_settings()
        headers = {"Authorization": f"Bearer {s.ai_service_token}"} if s.ai_service_token else {}
        _http = httpx.AsyncClient(
            base_url=s.ai_service_url.rstrip("/"), headers=headers,
            timeout=httpx.Timeout(connect=5.0, read=s.ai_request_timeout_seconds, write=120.0, pool=30.0),
        )
    return _http


async def close() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


def _headers() -> dict[str, str]:
    return {"content-type": "application/json", "x-request-id": logs.request_id.get()}


def _failure(response: httpx.Response) -> tuple[str, Usage | None]:
    try:
        body = ErrorResponse.model_validate_json(response.content)
        return body.error.message, body.usage
    except ValidationError:
        return f"AI service error ({response.status_code})", None


async def call(path: str, body: BaseModel, output: type[T], usage: UsageTag | None = None) -> T:
    """Run one single-call task. Raises AIError with a message that can be shown to the user."""
    try:
        response = await http().post(f"/v1{path}", content=body.model_dump_json(), headers=_headers())
    except httpx.HTTPError as e:
        log.error("AI service request %s failed: %r", path, e)
        raise AIError(UNREACHABLE) from e
    if response.status_code != 200:
        message, used = _failure(response)
        await record_usage(usage, used)
        log.warning("AI service %s -> %s: %s", path, response.status_code, message)
        raise AIError(message)
    result = TaskResponse[output].model_validate_json(response.content)
    await record_usage(usage, result.usage)
    return result.output


# ---------- guided conversation ----------


async def guide_system(body: GuideSystemIn) -> str:
    try:
        response = await http().post("/v1/guide/system", content=body.model_dump_json(), headers=_headers())
    except httpx.HTTPError as e:
        raise AIError(UNREACHABLE) from e
    if response.status_code != 200:
        raise AIError(_failure(response)[0])
    return GuideSystemOut.model_validate_json(response.content).system


async def guide_step(body: GuideStepIn, usage: UsageTag | None = None) -> AsyncIterator[TextEvent | ToolStartEvent | FinalEvent]:
    """One model call of the guide, streamed. Yields text and tool-start events, then one final event.
    Raises AIError if the step fails or the stream ends without a final event."""
    events = {"text": TextEvent, "tool_start": ToolStartEvent, "final": FinalEvent, "error": ErrorEvent}
    finished = False
    try:
        async with http().stream("POST", "/v1/guide/step", content=body.model_dump_json(), headers=_headers()) as response:
            if response.status_code != 200:
                await response.aread()
                raise AIError(_failure(response)[0])
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])
                event = events[data["type"]].model_validate(data)
                if isinstance(event, ErrorEvent):
                    raise AIError(event.message)
                if isinstance(event, FinalEvent):
                    finished = True
                    await record_usage(usage, event.usage)
                yield event
    except httpx.HTTPError as e:
        log.error("AI service guide step failed: %r", e)
        raise AIError(UNREACHABLE) from e
    if not finished:
        raise AIError(UNREACHABLE)
