"""Background job bookkeeping shared by the worker and the API: how a job is marked failed, what a
failure means for the thing the job was working on, and how jobs that will never finish are noticed.

A job row lives in the database of whoever owns the work (see core/queue.py)."""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AssessmentRun, AssessmentVersion, Evidence, FrameworkVersion, Job
from app.services import ai

log = logging.getLogger("jobs")

GENERIC_FAILURE = "Something went wrong while processing this. Please try again."
INTERRUPTED = "This took too long or was interrupted. Please try again."

# Seconds a job may run before the worker stops it (arq `timeout`), per job type.
TIMEOUTS = {
    "parse_framework": 1800, "generate_questions": 1800, "generate_outputs": 1800,
    "generate_intake": 600, "tailor_questions": 900, "process_evidence": 600, "cross_analyze": 600,
}
DEFAULT_TIMEOUT = 1800
# A job still "queued" or "running" this long after its time limit will never finish
# (the worker was killed, or the queue lost it).
STALE_MARGIN = timedelta(minutes=5)


def safe_message(error: BaseException) -> str:
    """What a user may be told about a failure. Only AI service messages are written for users;
    anything else (database errors, storage errors) may contain internals and is only logged."""
    return str(error) if isinstance(error, ai.AIError) else GENERIC_FAILURE


async def _framework_failed(db: AsyncSession, job: Job, message: str) -> None:
    version = await db.get(FrameworkVersion, job.ref_id)
    if version:
        version.parse_status, version.parse_error = "failed", message


async def _questions_failed(db: AsyncSession, job: Job, message: str) -> None:
    version = await db.get(AssessmentVersion, job.ref_id)
    if version:
        version.generation_status = "failed"


async def _intake_failed(db: AsyncSession, job: Job, message: str) -> None:
    run = await db.get(AssessmentRun, job.ref_id)
    if run and run.status == "intake":  # fall back to no intake: the assessment can still be answered untailored
        run.intake_summary, run.status = {"status": "skipped", "error": message}, "in_progress"


async def _tailoring_failed(db: AsyncSession, job: Job, message: str) -> None:
    run = await db.get(AssessmentRun, job.ref_id)
    if run and run.status == "intake":  # keep the original questions if tailoring fails
        run.intake_summary = {**(run.intake_summary or {}), "status": "tailor_failed"}
        run.status = "in_progress"


async def _evidence_failed(db: AsyncSession, job: Job, message: str) -> None:
    ev = await db.get(Evidence, job.ref_id)
    if ev and ev.processing_status != "ready":
        ev.processing_status, ev.processing_error = "failed", message


async def _outputs_failed(db: AsyncSession, job: Job, message: str) -> None:
    run = await db.get(AssessmentRun, job.ref_id)
    if run and run.status == "generating_outputs":  # back to an editable state so it can be submitted again
        run.status = "in_progress"


# What a failed job means for the thing it was working on, by job type.
ON_FAILURE: dict[str, Callable[[AsyncSession, Job, str], Awaitable[None]]] = {
    "parse_framework": _framework_failed,
    "generate_questions": _questions_failed,
    "generate_intake": _intake_failed,
    "tailor_questions": _tailoring_failed,
    "process_evidence": _evidence_failed,
    "generate_outputs": _outputs_failed,
}


async def fail(db: AsyncSession, job: Job, message: str) -> None:
    """Mark the job failed and put what it was working on back into a state people can act on.
    The caller commits."""
    job.status, job.error, job.finished_at = "failed", message[:2000], datetime.now(UTC)
    hook = ON_FAILURE.get(job.type)
    if hook:
        await hook(db, job, message)


async def expire_stale(db: AsyncSession, *ref_ids) -> int:
    """Fail the jobs for the given objects (a run, a file, a version) that can no longer finish.
    Called when those objects are read, so a killed worker or a lost queue entry can't leave them stuck."""
    now = datetime.now(UTC)
    open_jobs = (await db.execute(select(Job).where(Job.ref_id.in_(ref_ids), Job.status.in_(("queued", "running"))))).scalars().all()
    expired = 0
    for job in open_jobs:
        limit = timedelta(seconds=TIMEOUTS.get(job.type, DEFAULT_TIMEOUT)) + STALE_MARGIN
        if now - (job.started_at or job.created_at) > limit:
            log.warning("job %s (%s) never finished; marking it failed", job.id, job.type)
            await fail(db, job, INTERRUPTED)
            expired += 1
    if expired:
        await db.commit()
    return expired
