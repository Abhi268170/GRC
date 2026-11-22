"""Thin wrapper around the Anthropic SDK used by every AI feature.

- Streaming for every call (long documents/outputs never hit HTTP timeouts).
- Structured outputs via Pydantic models: results are schema-validated.
- Server-side refusal fallbacks enabled by default (`fallbacks="default"`)."""

import logging
import uuid
from dataclasses import dataclass
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from app.core.config import get_settings

log = logging.getLogger("ai")
T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(RuntimeError):
    pass


# List prices in USD per million tokens: (input, output, cache read, cache write).
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


@dataclass
class UsageTag:
    feature: str
    tenant_id: uuid.UUID | None = None  # whose database the usage is recorded in (None = control)
    run_id: uuid.UUID | None = None


def estimate_cost(model: str, usage: Any) -> float:
    p_in, p_out, p_read, p_write = PRICES.get(model, PRICES["claude-opus-5-5"])
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (usage.input_tokens * p_in + usage.output_tokens * p_out + read * p_read + write * p_write) / 1_000_000


async def record_usage(tag: UsageTag | None, model: str, usage: Any) -> None:
    """Log one call in its own transaction, so it counts even if the caller's work rolls back."""
    if tag is None:
        return
    from app.core.db import session_for
    from app.models import AiUsage

    try:
        async with session_for(tag.tenant_id) as db:
            db.add(AiUsage(
                run_id=tag.run_id, feature=tag.feature, model=model,
                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                cost_usd=estimate_cost(model, usage),
            ))
            await db.commit()
    except Exception:  # noqa: BLE001 - metering must never break the feature itself
        log.exception("could not record AI usage")


async def run_spend(db: Any, run_id: uuid.UUID) -> float:
    from sqlalchemy import func, select

    from app.models import AiUsage

    return float((await db.execute(select(func.coalesce(func.sum(AiUsage.cost_usd), 0)).where(AiUsage.run_id == run_id))).scalar())


_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        key = get_settings().anthropic_api_key
        if not key:
            raise AIError("ANTHROPIC_API_KEY is not configured")
        _client = anthropic.AsyncAnthropic(api_key=key, max_retries=3)
    return _client


def analysis_model() -> str:
    return get_settings().ai_model_analysis


def conversation_model() -> str:
    return get_settings().ai_model_conversation


async def structured(
    *,
    output: type[T],
    system: str,
    content: list[dict[str, Any]] | str,
    model: str | None = None,
    effort: str = "medium",
    max_tokens: int = 64000,
    usage: UsageTag | None = None,
) -> T:
    """One structured call. Raises AIError on refusal, truncation, or API failure."""
    try:
        async with client().beta.messages.stream(
            model=model or analysis_model(),
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=output,
            output_config={"effort": effort},
        ) as stream:
            message = await stream.get_final_message()
    except anthropic.APIStatusError as e:
        log.error("AI request failed (%s): %s request_id=%s", e.status_code, e.message,
                  getattr(e, "request_id", None))
        raise AIError(f"AI service error ({e.status_code})") from e
    except anthropic.APIConnectionError as e:
        raise AIError("Could not reach the AI service") from e

    await record_usage(usage, message.model, message.usage)
    log.info("AI %s in=%s out=%s stop=%s id=%s", output.__name__, message.usage.input_tokens,
             message.usage.output_tokens, message.stop_reason, message.id)
    if message.stop_reason == "refusal":
        raise AIError("The AI declined to process this request")
    if message.stop_reason == "max_tokens":
        raise AIError("The AI response was too long and was cut off")
    if message.parsed_output is None:
        raise AIError("The AI returned an unexpected response")
    return message.parsed_output
