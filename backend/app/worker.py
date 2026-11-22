"""Background worker (arq). Long-running AI and file-processing jobs run here.

Each job function receives the `job` row id and the tenant whose database holds that row
(None = the control database), marks the job running/done/failed, and updates the object
it works on. What a failure means for that object is in services/jobs.py. The fan-out
functions at the end do work that spans every company database."""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from arq import Retry, func
from arq.connections import RedisSettings
from sqlalchemy import select

from app.core import logs
from app.core.config import get_settings
from app.core.db import dispose_all, session_for
from app.models import AppUser, AssessmentRun, AssessmentVersion, Evidence, FrameworkVersion, Job, Notification
from app.services import ai, cross_analysis, evidence, framework_parser, intake, jobs, outputs, question_gen, tenants

log = logging.getLogger("worker")

CROSS_ANALYSIS_TRIES = 15  # waits for evidence to be read: one try every 8 seconds, two minutes in all


async def _run(job_id: str, tenant_id: str | None, work: Callable[[object, Job], Awaitable[dict]]) -> None:
    logs.request_id.set(f"job-{job_id[:8]}")
    async with session_for(uuid.UUID(tenant_id) if tenant_id else None) as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if job is None or job.status in ("done", "failed"):
            return  # unknown, or delivered again after it was already settled
        job.status, job.started_at, job.attempts = "running", datetime.now(UTC), job.attempts + 1
        await db.commit()
        try:
            job.result = await work(db, job)
            job.status, job.finished_at = "done", datetime.now(UTC)
            await db.commit()
        except Retry:
            await db.rollback()
            job = await db.get(Job, uuid.UUID(job_id))
            job.status = "queued"
            await db.commit()
            raise
        except BaseException as e:
            # Also when the worker stops the job (time limit, shutdown): the row must never stay "running".
            interrupted = isinstance(e, asyncio.CancelledError)
            log.error("job %s (%s) %s", job_id, job.type, "was interrupted" if interrupted else "failed", exc_info=not interrupted)
            await db.rollback()
            job = await db.get(Job, uuid.UUID(job_id))
            await jobs.fail(db, job, jobs.INTERRUPTED if interrupted else jobs.safe_message(e))
            await db.commit()
            if interrupted or not isinstance(e, Exception):
                raise


async def parse_framework(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        version = await db.get(FrameworkVersion, job.ref_id)
        version.parse_status, version.parse_error = "processing", None
        await db.commit()
        count = await framework_parser.parse_version(db, job.ref_id)
        version.parse_status = "done"
        await db.commit()
        return {"clauses": count}

    await _run(job_id, tenant_id, work)


async def generate_questions(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        version = await db.get(AssessmentVersion, job.ref_id)
        version.generation_status = "processing"
        await db.commit()
        result = await question_gen.generate(db, job.ref_id, job.payload.get("mode", "all"))
        version.generation_status = "done"
        await db.commit()
        return result

    await _run(job_id, tenant_id, work)


async def generate_intake(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        result = await intake.generate_intake(db, job.ref_id)
        await db.commit()
        return result

    await _run(job_id, tenant_id, work)


async def tailor_questions(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        result = await intake.tailor(db, job.ref_id)
        await db.commit()
        return result

    await _run(job_id, tenant_id, work)


async def process_evidence(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        ev = await db.get(Evidence, job.ref_id)
        ev.processing_status = "processing"
        await db.commit()
        result = await evidence.process(db, job.ref_id)
        await db.commit()
        return result

    await _run(job_id, tenant_id, work)


async def generate_outputs(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        result = await outputs.generate(db, job.ref_id)
        run = await db.get(AssessmentRun, job.ref_id)
        run.status = "in_review"
        await _notify_reviewers(db, run)
        await db.commit()
        return result

    await _run(job_id, tenant_id, work)


async def _notify_reviewers(db, run: AssessmentRun) -> None:
    admins = (await db.execute(select(AppUser.id).where(AppUser.platform_role == "tenant_admin", AppUser.is_active))).scalars().all()
    for uid in {run.started_by, *admins}:
        db.add(Notification(user_id=uid, type="run_submitted",
                            payload={"assessment_title": run.title, "run_id": str(run.id)}))


async def cross_analyze(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        try:
            result = await cross_analysis.analyze(db, job.ref_id, job.payload)
        except cross_analysis.EvidenceNotReady:
            if ctx.get("job_try", 1) >= CROSS_ANALYSIS_TRIES:
                # Out of tries: settle the job, or the page would wait for this analysis forever.
                return {"skipped": "the evidence was still being read"}
            raise Retry(defer=8) from None  # evidence still being read; try again shortly
        await db.commit()
        return result

    await _run(job_id, tenant_id, work)


# ---------- work that spans every company database (no job row) ----------


async def fanout_master_data(ctx: dict) -> int:
    """Master data or organisational roles changed: bring every company's copy up to date."""
    count = await tenants.sync_master_data_everywhere()
    log.info("master data synced to %d company database(s)", count)
    return count


async def fanout_deprecation(ctx: dict, version_id: str, payload: dict) -> int:
    """A newer assessment version was published: mark each company's copy of the old one and notify."""
    notices = await tenants.deprecate_everywhere(uuid.UUID(version_id), payload)
    log.info("assessment version %s deprecated: %d notice(s) sent", version_id, notices)
    return notices


async def ping(ctx: dict) -> str:
    return "pong"


async def startup(ctx: dict) -> None:
    logs.setup(get_settings().log_level)


async def shutdown(ctx: dict) -> None:
    await ai.close()
    await dispose_all()


def _job(coroutine, **options):
    """A job function with its own time limit (services/jobs.py). One try unless said otherwise:
    a job that failed once is reported to the user, who decides whether to try again."""
    return func(coroutine, timeout=jobs.TIMEOUTS.get(coroutine.__name__, jobs.DEFAULT_TIMEOUT),
                max_tries=options.pop("max_tries", 1), **options)


class WorkerSettings:
    functions = [
        ping,
        _job(parse_framework), _job(generate_questions), _job(generate_intake), _job(tailor_questions),
        _job(process_evidence), _job(generate_outputs),
        _job(cross_analyze, max_tries=CROSS_ANALYSIS_TRIES),
        # keep_result=0 frees the fixed job id as soon as the fan-out ends, so the next change can queue one.
        func(fanout_master_data, timeout=1800, max_tries=2, keep_result=0),
        func(fanout_deprecation, timeout=1800, max_tries=1),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = get_settings().worker_max_jobs
    health_check_interval = 30  # `arq --check app.worker.WorkerSettings` reads this heartbeat
