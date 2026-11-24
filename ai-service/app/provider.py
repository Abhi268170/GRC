"""The only module that talks to the model provider (the Anthropic SDK).

- Streaming for every call (long documents and outputs never hit HTTP timeouts).
- Structured outputs via Pydantic models: results are schema-validated.
- Server-side refusal fallbacks enabled by default (`fallbacks="default"`)."""

import asyncio
import logging
from typing import Any, TypeVar

import anthropic
from ai_contracts import (
    ERROR_INVALID_OUTPUT,
    ERROR_PROVIDER,
    ERROR_REFUSAL,
    ERROR_TRUNCATED,
    ERROR_UNAVAILABLE,
    Usage,
)
from pydantic import BaseModel

from app.config import get_settings

log = logging.getLogger("provider")
T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

# List prices in USD per million tokens: (input, output, cache read, cache write).
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


class AIFailure(Exception):
    """A model call that failed in a way the caller should hear about."""

    def __init__(self, code: str, message: str, status: int, usage: Usage | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.usage = code, message, status, usage


def usage_of(model: str, usage: Any) -> Usage:
    p_in, p_out, p_read, p_write = PRICES.get(model, PRICES["claude-opus-5-5"])
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cost = (usage.input_tokens * p_in + usage.output_tokens * p_out + read * p_read + write * p_write) / 1_000_000
    return Usage(model=model, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                 cache_read_tokens=read, cache_write_tokens=write, cost_usd=round(cost, 6))


_client: anthropic.AsyncAnthropic | None = None
_slots: asyncio.Semaphore | None = None


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        s = get_settings()
        if not s.anthropic_api_key:
            raise AIFailure(ERROR_UNAVAILABLE, "ANTHROPIC_API_KEY is not configured", 503)
        _client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key, max_retries=s.ai_max_retries)
    return _client


def slots() -> asyncio.Semaphore:
    """Limits model calls running at once, so a burst of work queues here instead of hitting rate limits."""
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(get_settings().ai_max_concurrent_calls)
    return _slots


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def analysis_model() -> str:
    return get_settings().ai_model_analysis


def conversation_model() -> str:
    return get_settings().ai_model_conversation


def provider_failure(e: Exception) -> AIFailure:
    """Map the SDK's errors to what the caller is told. Most specific first."""
    if isinstance(e, anthropic.RateLimitError):
        log.warning("provider rate limit: %s request_id=%s", e.message, getattr(e, "request_id", None))
        return AIFailure(ERROR_UNAVAILABLE, "The AI service is busy. Try again in a moment.", 503)
    if isinstance(e, anthropic.APIStatusError):
        log.error("provider request failed (%s): %s request_id=%s", e.status_code, e.message,
                  getattr(e, "request_id", None))
        return AIFailure(ERROR_PROVIDER, f"AI service error ({e.status_code})", 502)
    if isinstance(e, anthropic.APIConnectionError):
        log.error("provider unreachable: %s", e)
        return AIFailure(ERROR_UNAVAILABLE, "Could not reach the AI service", 503)
    raise e


async def structured(
    *,
    output: type[T],
    system: str,
    content: list[dict[str, Any]] | str,
    model: str | None = None,
    effort: str = "medium",
    max_tokens: int = 64000,
    cache_system: bool = False,
) -> tuple[T, Usage]:
    """One structured call. Raises AIFailure on refusal, truncation, or provider failure.
    cache_system: the system prompt is long and the same on every call, so let the provider cache it."""
    api = client()
    system_blocks: Any = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if cache_system else system
    try:
        async with slots(), api.beta.messages.stream(
            model=model or analysis_model(),
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=system_blocks,
            messages=[{"role": "user", "content": content}],
            output_format=output,
            output_config={"effort": effort},
        ) as stream:
            message = await stream.get_final_message()
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        raise provider_failure(e) from e

    usage = usage_of(message.model, message.usage)
    log.info("%s model=%s in=%s out=%s stop=%s cost=%.4f id=%s", output.__name__, message.model,
             usage.input_tokens, usage.output_tokens, message.stop_reason, usage.cost_usd, message.id)
    if message.stop_reason == "refusal":
        raise AIFailure(ERROR_REFUSAL, "The AI declined to process this request", 422, usage)
    if message.stop_reason == "max_tokens":
        raise AIFailure(ERROR_TRUNCATED, "The AI response was too long and was cut off", 422, usage)
    if message.parsed_output is None:
        raise AIFailure(ERROR_INVALID_OUTPUT, "The AI returned an unexpected response", 502, usage)
    return message.parsed_output, usage
