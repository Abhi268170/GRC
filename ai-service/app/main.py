"""AI service: every model call of the platform goes through here.

It is stateless and has no database. The backend sends structured data, this service owns the
prompts, output schemas, tool definitions and model settings, and returns validated results
with what the call used. See packages/ai_contracts for the request and response models."""

import hmac
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated

from ai_contracts import (
    ERROR_BAD_REQUEST,
    ERROR_UNAUTHORIZED,
    CrossAnalysisIn,
    CrossResult,
    DomainQuestion,
    ErrorBody,
    ErrorResponse,
    EvidenceDigest,
    EvidenceDigestIn,
    GenerateQuestionIn,
    GuideStepIn,
    GuideSystemIn,
    GuideSystemOut,
    IntakeIn,
    IntakeQuestions,
    Narrative,
    NogaClassifyIn,
    NogaRanking,
    ParsedFramework,
    ParseFrameworkIn,
    ResultsIn,
    TagQuestionIn,
    Tags,
    TailorIn,
    Tailoring,
    TaskResponse,
    Usage,
)
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app import guide, logs, provider, tasks
from app.config import get_settings

log = logging.getLogger("ai-service")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    logs.setup(s.log_level)
    if not s.anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY is not set: every task will answer 503")
    if not s.ai_service_token:
        log.warning("AI_SERVICE_TOKEN is not set: requests are not authenticated (development only)")
    yield
    await provider.close()


app = FastAPI(title="TrustUp AI service", version="0.1.0", lifespan=lifespan)


def _error(status: int, code: str, message: str, usage: Usage | None = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message), usage=usage)
    return JSONResponse(status_code=status, content=body.model_dump())


@app.exception_handler(provider.AIFailure)
async def ai_failure(request: Request, exc: provider.AIFailure) -> JSONResponse:
    return _error(exc.status, exc.code, exc.message, exc.usage)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    where = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()[:5])
    return _error(422, ERROR_BAD_REQUEST, f"Invalid request: {where}")


@app.exception_handler(ValueError)
async def bad_input(request: Request, exc: ValueError) -> JSONResponse:
    return _error(422, ERROR_BAD_REQUEST, str(exc))


@app.middleware("http")
async def request_log(request: Request, call_next: Callable[[Request], Awaitable]):
    """Carry the caller's request id (or make one), and log one line per request."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    logs.request_id.set(rid)  # each request runs in its own task, so this doesn't leak into other requests
    started = time.perf_counter()
    response = await call_next(request)
    if not request.url.path.startswith("/health"):
        log.info("%s %s -> %s in %.1fs", request.method, request.url.path, response.status_code,
                 time.perf_counter() - started)
    response.headers["x-request-id"] = rid
    return response


async def authenticated(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().ai_service_token
    if not expected:
        return  # development: the settings refuse to start without a token in production
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "Invalid or missing service token")


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    code = ERROR_UNAUTHORIZED if exc.status_code == 401 else ERROR_BAD_REQUEST
    return _error(exc.status_code, code, str(exc.detail))


# ---------- health (not authenticated) ----------


@app.get("/health/live")
async def live() -> dict:
    return {"status": "ok"}


@app.get("/health")
async def health() -> JSONResponse:
    s = get_settings()
    ready = bool(s.anthropic_api_key)
    body = {"status": "ok" if ready else "degraded",
            "checks": {"provider_key": "ok" if ready else "missing"},
            "models": {"conversation": s.ai_model_conversation, "analysis": s.ai_model_analysis}}
    return JSONResponse(status_code=200 if ready else 503, content=body)


# ---------- tasks ----------

v1 = APIRouter(prefix="/v1", dependencies=[Depends(authenticated)])


def task(path: str, input_model: type[BaseModel], output_model: type[BaseModel], run: Callable) -> None:
    """Register one single-call task: POST {path} with input_model -> {"output": ..., "usage": ...}."""

    async def endpoint(body: input_model):  # type: ignore[valid-type]
        output, usage = await run(body)
        return TaskResponse[output_model](output=output, usage=usage)

    endpoint.__name__ = run.__name__
    v1.post(path, response_model=TaskResponse[output_model], name=run.__name__,
            responses={422: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})(endpoint)


task("/framework/parse", ParseFrameworkIn, ParsedFramework, tasks.parse_framework)
task("/questions/generate", GenerateQuestionIn, DomainQuestion, tasks.generate_question)
task("/questions/tag", TagQuestionIn, Tags, tasks.tag_question)
task("/intake/questions", IntakeIn, IntakeQuestions, tasks.intake_questions)
task("/intake/tailor", TailorIn, Tailoring, tasks.tailor)
task("/evidence/digest", EvidenceDigestIn, EvidenceDigest, tasks.evidence_digest)
task("/cross-analysis", CrossAnalysisIn, CrossResult, tasks.cross_analysis)
task("/results/narrative", ResultsIn, Narrative, tasks.results_narrative)
task("/noga/classify", NogaClassifyIn, NogaRanking, tasks.classify_noga)


@v1.post("/guide/system", response_model=GuideSystemOut)
async def guide_system(body: GuideSystemIn) -> GuideSystemOut:
    return GuideSystemOut(system=guide.build_system(body))


@v1.post("/guide/step")
async def guide_step(body: GuideStepIn) -> StreamingResponse:
    """Server-Sent Events: `text` and `tool_start` events while the model writes, then `final` or `error`."""

    async def events() -> AsyncIterator[str]:
        async for event in guide.step(body):
            yield f"data: {event.model_dump_json()}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


app.include_router(v1)
