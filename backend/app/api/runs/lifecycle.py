"""A run from start to approval: list, start, intake, assignment, submission, review, results, report."""

import asyncio
import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response as RawResponse
from sqlalchemy import func, select
from app.core.auth import ControlDB, TenantDB, TenantMember
from app.core.config import get_settings
from app.core.queue import enqueue
from app.models import (
    ActionItem,
    AppUser,
    AssessmentRun,
    AssessmentVersion,
    Report,
    ReviewComment,
    Risk,
    RunDomain,
)
from app.services import ai, export, jobs, snapshot
from app.services import runs as svc
from app.core.uploads import content_disposition
from app.api.runs.schemas import AssignIn, ChangesIn, IntakeIn, Results, RunDetail, RunSummary, StartIn
from app.api.runs.views import _ai_paused, _domain_summary, _latest_job, _notify, _require_reviewer, _reviewers, _summary, action_out, risk_out

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunSummary])
async def list_runs(db: TenantDB, me: TenantMember) -> list[RunSummary]:
    runs = (await db.execute(select(AssessmentRun).order_by(AssessmentRun.created_at.desc()))).scalars().all()
    return [await _summary(db, r) for r in runs]

@router.post("", response_model=RunSummary, status_code=201)
async def start_run(body: StartIn, db: TenantDB, control: ControlDB, me: TenantMember) -> RunSummary:
    published = await control.get(AssessmentVersion, body.assessment_version_id)
    if published is None or published.status != "published":
        raise HTTPException(404, "This assessment isn't available")
    # Starting a run costs an AI call, so the number of open runs and the monthly AI budget are capped.
    open_runs = (await db.execute(select(func.count()).select_from(AssessmentRun).where(AssessmentRun.status != "approved"))).scalar()
    if open_runs >= get_settings().max_open_runs_per_tenant:
        raise HTTPException(409, "Your company has too many assessments in progress. Finish or approve one first.")
    if await ai.company_over_budget(db):
        raise HTTPException(409, "Your company has used its AI allowance for this month, so new assessments can't be started.")
    # The run works on this company's own copy of the assessment (same ids as the original).
    await snapshot.copy_assessment_version(control, db, published.id)
    version = await db.get(AssessmentVersion, published.id)
    run = await svc.create_run(db, me, version)
    run.intake_summary = {"status": "generating"}
    await enqueue(db, type="generate_intake", ref_type="assessment_run", ref_id=run.id)
    return await _summary(db, run)

@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: uuid.UUID, db: TenantDB, me: TenantMember) -> RunDetail:
    run = await svc.get_run(db, me, run_id)
    await jobs.expire_stale(db, run.id)  # a job that can no longer finish must not leave the run stuck
    version = await db.get(AssessmentVersion, run.assessment_version_id)
    scope = await svc.load_run_scope(db, run.assessment_version_id)
    evals = await svc.evaluations_by_req(db, run.id)
    rds = (await db.execute(select(RunDomain).where(RunDomain.run_id == run.id))).scalars().all()
    order = [d.avd_id for d in scope.domains]
    rds = sorted(rds, key=lambda x: order.index(x.assessment_version_domain_id))
    intake_job = await _latest_job(db, run.id, ("generate_intake", "tailor_questions"))
    out_job = await _latest_job(db, run.id, ("generate_outputs",))
    base = await _summary(db, run)
    return RunDetail(
        **base.model_dump(), assessment_description=version.description, intake=run.intake_summary,
        intake_job=intake_job.status if intake_job else None,
        outputs_job_status=out_job.status if out_job else None, outputs_job_error=out_job.error if out_job else None,
        domains=[await _domain_summary(db, run, rd, scope, evals, me) for rd in rds],
        can_review=svc.can_review(me, run), is_admin=me.platform_role == "tenant_admin",
        ai_paused=await _ai_paused(db, run),
    )

@router.post("/{run_id}/intake", response_model=RunDetail)
async def submit_intake(run_id: uuid.UUID, body: IntakeIn, db: TenantDB, me: TenantMember) -> RunDetail:
    run = await svc.get_run(db, me, run_id, lock=True)
    _require_reviewer(me, run, "answer the intake")
    if run.status != "intake" or (run.intake_summary or {}).get("status") != "ready":
        raise HTTPException(409, "The intake isn't ready for answers")
    intake = dict(run.intake_summary)
    intake["answers"], intake["status"] = {k: v.strip() for k, v in body.answers.items()}, "tailoring"
    run.intake_summary = intake
    await enqueue(db, type="tailor_questions", ref_type="assessment_run", ref_id=run.id)
    return await get_run(run_id, db, me)

@router.post("/{run_id}/intake/skip", response_model=RunDetail)
async def skip_intake(run_id: uuid.UUID, db: TenantDB, me: TenantMember) -> RunDetail:
    run = await svc.get_run(db, me, run_id, lock=True)
    _require_reviewer(me, run, "skip the intake")
    if run.status != "intake" or (run.intake_summary or {}).get("status") == "tailoring":
        raise HTTPException(409, "The intake can't be skipped now")
    run.intake_summary = {**(run.intake_summary or {}), "status": "skipped"}
    run.status = "in_progress"
    await db.commit()
    return await get_run(run_id, db, me)

@router.put("/{run_id}/domains/{run_domain_id}/assignee", response_model=RunDetail)
async def assign(run_id: uuid.UUID, run_domain_id: uuid.UUID, body: AssignIn, db: TenantDB, me: TenantMember) -> RunDetail:
    run = await svc.get_run(db, me, run_id)
    if not svc.can_review(me, run):
        raise HTTPException(403, "Only the person who started this assessment or an admin can assign domains")
    rd = await svc.get_domain(db, run, run_domain_id)
    if body.user_id:
        assignee = await db.get(AppUser, body.user_id)
        if assignee is None or not assignee.is_active:
            raise HTTPException(422, "Unknown team member")
        if body.user_id != me.id:
            scope = await svc.load_run_scope(db, run.assessment_version_id)
            name = next(d.name for d in scope.domains if d.avd_id == rd.assessment_version_domain_id)
            await _notify(db, run, {body.user_id}, "domain_assigned", {"domain_name": name, "assessment_title": run.title, "run_id": str(run.id)})
    rd.assignee_id = body.user_id
    await db.commit()
    return await get_run(run_id, db, me)

@router.post("/{run_id}/submit", response_model=RunDetail)
async def submit(run_id: uuid.UUID, db: TenantDB, me: TenantMember) -> RunDetail:
    run = await svc.get_run(db, me, run_id, lock=True)
    _require_reviewer(me, run, "submit it")
    if run.status not in ("in_progress", "changes_requested"):
        raise HTTPException(409, "This assessment can't be submitted now")
    if await ai.company_over_budget(db):
        raise HTTPException(409, "Your company has used its AI allowance for this month, so results can't be written yet.")
    statuses = (await db.execute(select(RunDomain.status).where(RunDomain.run_id == run.id))).scalars().all()
    if any(s != "completed" for s in statuses):
        raise HTTPException(409, "Complete every domain before submitting")
    run.status, run.submitted_at = "generating_outputs", svc.now()
    await enqueue(db, type="generate_outputs", ref_type="assessment_run", ref_id=run.id)
    return await get_run(run_id, db, me)

@router.post("/{run_id}/request-changes", response_model=RunDetail)
async def request_changes(run_id: uuid.UUID, body: ChangesIn, db: TenantDB, me: TenantMember) -> RunDetail:
    run = await svc.get_run(db, me, run_id, lock=True)
    if not svc.can_review(me, run):
        raise HTTPException(403, "Only the person who started this assessment or an admin can review it")
    if run.status != "in_review":
        raise HTTPException(409, "This assessment isn't in review")
    rd = await svc.get_domain(db, run, body.run_domain_id)
    rd.status = "changes_requested"
    run.status = "changes_requested"
    db.add(ReviewComment(run_id=run.id, run_domain_id=rd.id, target_type="domain", comment=body.comment, created_by=me.id))
    scope = await svc.load_run_scope(db, run.assessment_version_id)
    name = next(d.name for d in scope.domains if d.avd_id == rd.assessment_version_domain_id)
    recipients = {rd.assignee_id or run.started_by} - {me.id}
    await _notify(db, run, recipients, "changes_requested", {"domain_name": name, "assessment_title": run.title, "run_id": str(run.id)})
    await db.commit()
    return await get_run(run_id, db, me)

@router.post("/{run_id}/approve", response_model=RunDetail)
async def approve(run_id: uuid.UUID, db: TenantDB, me: TenantMember) -> RunDetail:
    run = await svc.get_run(db, me, run_id, lock=True)
    if not svc.can_review(me, run):
        raise HTTPException(403, "Only the person who started this assessment or an admin can approve it")
    if run.status != "in_review":
        raise HTTPException(409, "This assessment isn't in review")
    for item in (await db.execute(select(ActionItem).where(ActionItem.run_id == run.id, ActionItem.status == "suggested"))).scalars():
        item.status = "open"  # suggestions not dismissed during review are accepted on approval
    for risk in (await db.execute(select(Risk).where(Risk.run_id == run.id, Risk.status == "suggested"))).scalars():
        risk.status = "open"
    report = (await db.execute(select(Report).where(Report.run_id == run.id))).scalar_one_or_none()
    if report:
        report.status = "final"
    run.status, run.approved_by, run.approved_at = "approved", me.id, svc.now()
    await _notify(db, run, (await _reviewers(db, run)) - {me.id}, "run_approved", {"assessment_title": run.title, "run_id": str(run.id)})
    await db.commit()
    return await get_run(run_id, db, me)

@router.get("/{run_id}/results", response_model=Results)
async def results(run_id: uuid.UUID, db: TenantDB, me: TenantMember) -> Results:
    run = await svc.get_run(db, me, run_id)
    scope = await svc.load_run_scope(db, run.assessment_version_id)
    report = (await db.execute(select(Report).where(Report.run_id == run.id))).scalar_one_or_none()
    actions = (await db.execute(select(ActionItem).where(ActionItem.run_id == run.id).order_by(ActionItem.created_at))).scalars().all()
    risks = (await db.execute(select(Risk).where(Risk.run_id == run.id).order_by((Risk.likelihood * Risk.impact).desc()))).scalars().all()
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return Results(
        report=report.content if report else None, report_status=report.status if report else None,
        actions=sorted([await action_out(db, scope, a) for a in actions], key=lambda a: order.get(a.priority or "", 9)),
        risks=[await risk_out(db, scope, r) for r in risks],
    )

@router.get("/{run_id}/report.{fmt}")
async def download_report(run_id: uuid.UUID, fmt: str, db: TenantDB, me: TenantMember) -> RawResponse:
    if fmt not in ("pdf", "docx"):
        raise HTTPException(404, "Unknown format")
    data = await results(run_id, db, me)
    if data.report is None:
        raise HTTPException(404, "The report isn't ready yet")
    live = lambda items: [i.model_dump() for i in items if i.status != "dismissed"]  # noqa: E731
    acts, rsks = live(data.actions), live(data.risks)
    if fmt == "pdf":
        body, media = await asyncio.to_thread(export.to_pdf, data.report, acts, rsks), "application/pdf"
    else:
        body = await asyncio.to_thread(export.to_docx, data.report, acts, rsks)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    name = "".join(ch if ch.isalnum() else "-" for ch in data.report["title"]).strip("-").lower() or "assessment"
    return RawResponse(body, media_type=media, headers={"content-disposition": content_disposition(f"{name}-report.{fmt}")})
