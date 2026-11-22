"""Background worker (arq). Long-running AI and file-processing jobs run here.

Each job function receives the `job` row id and the tenant whose database holds that row
(None = the control database), marks the job running/done/failed, and updates the object
it works on. The fan-out functions at the end do work that spans every company database."""

import logging
import traceback
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from arq import Retry
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.db import session_for
from app.models import AssessmentRun, AssessmentVersion, Evidence, FrameworkVersion, Job
from app.services import cross_analysis, evidence, framework_parser, intake, outputs, question_gen, tenants

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")


async def _run(job_id: str, tenant_id: str | None, work: Callable[[object, Job], Awaitable[dict]], on_fail=None) -> None:
    async with session_for(uuid.UUID(tenant_id) if tenant_id else None) as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if job is None:
            return
        job.status, job.started_at, job.attempts = "running", datetime.now(UTC), job.attempts + 1
        await db.commit()
        try:
            job.result = await work(db, job)
            job.status = "done"
        except Retry:
            await db.rollback()
            job = await db.get(Job, uuid.UUID(job_id))
            job.status = "queued"
            await db.commit()
            raise
        except Exception as e:  # noqa: BLE001
            await db.rollback()
            job = await db.get(Job, uuid.UUID(job_id))
            job.status, job.error = "failed", str(e)[:2000]
            log.error("job %s failed: %s", job_id, traceback.format_exc())
            if on_fail:
                await on_fail(db, job, str(e))
        job.finished_at = datetime.now(UTC)
        await db.commit()


async def parse_framework(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        version = await db.get(FrameworkVersion, job.ref_id)
        version.parse_status, version.parse_error = "processing", None
        await db.commit()
        count = await framework_parser.parse_version(db, job.ref_id)
        version.parse_status = "done"
        await db.commit()
        return {"clauses": count}

    async def fail(db, job: Job, error: str) -> None:
        version = await db.get(FrameworkVersion, job.ref_id)
        if version:
            version.parse_status, version.parse_error = "failed", error[:2000]

    await _run(job_id, tenant_id, work, fail)


async def generate_questions(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        version = await db.get(AssessmentVersion, job.ref_id)
        version.generation_status = "processing"
        await db.commit()
        result = await question_gen.generate(db, job.ref_id, job.payload.get("mode", "all"))
        version.generation_status = "done"
        await db.commit()
        return result

    async def fail(db, job: Job, error: str) -> None:
        version = await db.get(AssessmentVersion, job.ref_id)
        if version:
            version.generation_status = "failed"

    await _run(job_id, tenant_id, work, fail)


async def generate_intake(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        result = await intake.generate_intake(db, job.ref_id)
        await db.commit()
        return result

    async def fail(db, job: Job, error: str) -> None:
        run = await db.get(AssessmentRun, job.ref_id)
        if run:  # fall back to no intake: the assessment can still be answered untailored
            run.intake_summary, run.status = {"status": "skipped", "error": error[:500]}, "in_progress"

    await _run(job_id, tenant_id, work, fail)


async def tailor_questions(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        result = await intake.tailor(db, job.ref_id)
        await db.commit()
        return result

    async def fail(db, job: Job, error: str) -> None:
        run = await db.get(AssessmentRun, job.ref_id)
        if run:  # keep the original questions if tailoring fails
            run.intake_summary = {**(run.intake_summary or {}), "status": "tailor_failed"}
            run.status = "in_progress"

    await _run(job_id, tenant_id, work, fail)


async def process_evidence(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        ev = await db.get(Evidence, job.ref_id)
        ev.processing_status = "processing"
        await db.commit()
        result = await evidence.process(db, job.ref_id)
        await db.commit()
        return result

    async def fail(db, job: Job, error: str) -> None:
        ev = await db.get(Evidence, job.ref_id)
        if ev:
            ev.processing_status, ev.processing_error = "failed", error[:2000]

    await _run(job_id, tenant_id, work, fail)


async def generate_outputs(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        result = await outputs.generate(db, job.ref_id)
        run = await db.get(AssessmentRun, job.ref_id)
        run.status = "in_review"
        await _notify_reviewers(db, run)
        await db.commit()
        return result

    async def fail(db, job: Job, error: str) -> None:
        run = await db.get(AssessmentRun, job.ref_id)
        if run:  # back to an editable state so it can be submitted again
            run.status = "in_progress"

    await _run(job_id, tenant_id, work, fail)


async def _notify_reviewers(db, run: AssessmentRun) -> None:
    from sqlalchemy import select

    from app.models import AppUser, Notification

    admins = (await db.execute(select(AppUser.id).where(AppUser.platform_role == "tenant_admin", AppUser.is_active))).scalars().all()
    for uid in {run.started_by, *admins}:
        db.add(Notification(user_id=uid, type="run_submitted",
                            payload={"assessment_title": run.title, "run_id": str(run.id)}))


async def cross_analyze(ctx: dict, job_id: str, tenant_id: str | None = None) -> None:
    async def work(db, job: Job) -> dict:
        try:
            result = await cross_analysis.analyze(db, job.ref_id, job.payload)
        except cross_analysis.EvidenceNotReady:
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


class WorkerSettings:
    functions = [ping, parse_framework, generate_questions, generate_intake, tailor_questions, process_evidence, generate_outputs,
                 cross_analyze, fanout_master_data, fanout_deprecation]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = 1800
    max_tries = 15  # only jobs that raise Retry (cross-analysis waiting for evidence) are retried
    max_jobs = 4
