"""Tenant assessment runs: start, intake, domains, guided conversation, evidence, verification,
submission, review and approval, results and report export."""

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response as RawResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.auth import ControlDB, TenantDB, TenantMember
from app.core.config import get_settings
from app.core.db import session_for, tenant_of
from app.core.queue import enqueue
from app.core.storage import get_object, put_object
from app.models import (
    ActionItem,
    ActionItemRequirement,
    AppUser,
    AssessmentRun,
    AssessmentVersion,
    Conversation,
    ConversationMessage,
    EvaluationCitation,
    Evidence,
    Framework,
    FrameworkClause,
    FrameworkVersion,
    Job,
    Notification,
    Report,
    RequirementClauseMap,
    RequirementEvaluation,
    Response,
    ReviewComment,
    Risk,
    RiskRequirement,
    RunDomain,
    RunQuestion,
    RunRollup,
)
from app.services import ai, export, guide, jobs, snapshot
from app.services import runs as svc
from app.core.uploads import clean_filename, content_disposition, read_limited
from app.services.documents import ALLOWED, IMAGES, PDF, guess_type, looks_like

router = APIRouter(prefix="/runs", tags=["runs"])
MAX_EVIDENCE = 25 * 1024 * 1024


# ---------- schemas ----------


class StartIn(BaseModel):
    assessment_version_id: uuid.UUID


class Person(BaseModel):
    id: uuid.UUID
    full_name: str


class DomainSummary(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    assignee: Person | None
    questions_total: int
    questions_done: int
    requirements_total: int
    requirements_rated: int
    requirements_verified: int
    can_work: bool
    score: float | None
    open_comments: int


class RunSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    version: int
    version_deprecated: bool
    started_by: Person
    started_at: datetime | None
    approved_at: datetime | None
    progress: int  # % of requirements verified
    domains_total: int
    domains_completed: int
    score: float | None


class RunDetail(RunSummary):
    assessment_description: str | None
    intake: dict | None
    intake_job: str | None
    outputs_job_status: str | None
    outputs_job_error: str | None
    domains: list[DomainSummary]
    can_review: bool
    is_admin: bool
    ai_paused: bool  # the run's AI budget is used up; finish by rating manually


class IntakeIn(BaseModel):
    answers: dict[Annotated[str, Field(max_length=16)], Annotated[str, Field(max_length=2000)]] = Field(max_length=20)


class AssignIn(BaseModel):
    user_id: uuid.UUID | None


class MessageIn(BaseModel):
    content: str = Field(default="", max_length=4000)
    evidence_ids: list[uuid.UUID] = Field(default=[], max_length=20)


class NaIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class EvaluationIn(BaseModel):
    rating: int | None = Field(default=None, ge=0, le=4)
    is_na: bool = False
    na_reason: str | None = Field(default=None, max_length=2000)


class ChangesIn(BaseModel):
    run_domain_id: uuid.UUID
    comment: str = Field(min_length=3, max_length=4000)


class EvidenceOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    processing_status: str
    summary: str | None
    uploaded_by: uuid.UUID
    created_at: datetime


class Citation(BaseModel):
    evidence_id: uuid.UUID | None
    evidence_filename: str | None
    response_id: uuid.UUID | None
    excerpt: str | None


class EvaluationOut(BaseModel):
    id: uuid.UUID
    rating: int | None
    is_na: bool
    na_reason: str | None
    rationale: str
    ai_rating: int | None
    ai_is_na: bool | None
    status: str
    verified_by: Person | None
    answer: str | None
    citations: list[Citation]


class RequirementState(BaseModel):
    id: uuid.UUID
    key: str
    control: str
    statement: str
    guidance: str  # how to meet it
    evidence: list[str]  # what can be checked to show the requirement is met
    mandatory: bool | None
    clauses: list[dict]
    evaluation: EvaluationOut | None


class QuestionState(BaseModel):
    id: uuid.UUID
    kind: str
    parent_id: uuid.UUID | None
    text: str
    help_text: str | None
    status: str
    proposed_na: bool
    proposed_na_reason: str | None
    requirement_keys: list[str]
    answer: str | None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    data: dict | None
    author: Person | None
    created_at: datetime


class Workspace(BaseModel):
    run_id: uuid.UUID
    run_status: str
    domain: DomainSummary
    current_question_id: uuid.UUID | None
    questions: list[QuestionState]
    requirements: list[RequirementState]
    messages: list[MessageOut]
    evidence: list[EvidenceOut]
    comments: list[dict]
    editable: bool
    ai_paused: bool
    analysis_pending: bool  # background cross-analysis queued or running for this run


# ---------- helpers ----------


async def _person(db: TenantDB, user_id: uuid.UUID | None) -> Person | None:
    if user_id is None:
        return None
    u = await db.get(AppUser, user_id)
    return Person(id=u.id, full_name=u.full_name) if u else None


async def _domain_summary(db: TenantDB, run: AssessmentRun, rd: RunDomain, scope: svc.RunScope, evals: dict, me: AppUser) -> DomainSummary:
    name = next(d.name for d in scope.domains if d.avd_id == rd.assessment_version_domain_id)
    qs = (await db.execute(select(RunQuestion.status).where(RunQuestion.run_domain_id == rd.id, RunQuestion.kind == "base"))).scalars().all()
    reqs = scope.reqs_for_domain(rd.assessment_version_domain_id)
    rated = [evals[r.id] for r in reqs if r.id in evals and evals[r.id].status != "awaiting_ai"]
    score = (await db.execute(select(RunRollup.score).where(RunRollup.run_id == run.id, RunRollup.level == "domain",
                                                             RunRollup.ref_id == rd.assessment_version_domain_id))).scalar()
    comments = (await db.execute(select(func.count()).where(ReviewComment.run_domain_id == rd.id, ReviewComment.resolved_at.is_(None)))).scalar()
    return DomainSummary(
        id=rd.id, name=name, status=rd.status, assignee=await _person(db, rd.assignee_id),
        questions_total=len(qs), questions_done=sum(1 for s in qs if s != "pending"),
        requirements_total=len(reqs), requirements_rated=len(rated),
        requirements_verified=sum(1 for e in rated if e.status in ("verified", "overridden")),
        can_work=svc.can_work_on(me, run, rd), score=float(score) if score is not None else None, open_comments=comments,
    )


async def _summary(db: TenantDB, run: AssessmentRun) -> RunSummary:
    version = await db.get(AssessmentVersion, run.assessment_version_id)
    scope = await svc.load_run_scope(db, run.assessment_version_id)
    evals = await svc.evaluations_by_req(db, run.id)
    total = len(scope.by_id)
    verified = sum(1 for e in evals.values() if e.status in ("verified", "overridden"))
    domains = (await db.execute(select(RunDomain.status).where(RunDomain.run_id == run.id))).scalars().all()
    score = (await db.execute(select(RunRollup.score).where(RunRollup.run_id == run.id, RunRollup.level == "assessment"))).scalar()
    return RunSummary(
        id=run.id, title=run.title or version.title, status=run.status, version=version.version,
        version_deprecated=version.status == "deprecated", started_by=await _person(db, run.started_by),
        started_at=run.started_at, approved_at=run.approved_at, progress=round(100 * verified / total) if total else 0,
        domains_total=len(domains), domains_completed=sum(1 for s in domains if s == "completed"),
        score=float(score) if score is not None else None,
    )


async def _latest_job(db: TenantDB, run_id: uuid.UUID, types: tuple[str, ...]) -> Job | None:
    return (await db.execute(select(Job).where(Job.ref_id == run_id, Job.type.in_(types)).order_by(Job.created_at.desc()).limit(1))).scalar_one_or_none()


async def _ai_paused(db: TenantDB, run: AssessmentRun) -> bool:
    return await ai.over_budget(db, run.id)


async def _notify(db: TenantDB, run: AssessmentRun, user_ids: set[uuid.UUID], type: str, payload: dict) -> None:
    for uid in user_ids:
        db.add(Notification(user_id=uid, type=type, payload=payload))


async def _reviewers(db: TenantDB, run: AssessmentRun) -> set[uuid.UUID]:
    admins = (await db.execute(select(AppUser.id).where(AppUser.platform_role == "tenant_admin",
                                                        AppUser.is_active))).scalars().all()
    return {run.started_by, *admins}


# ---------- runs ----------


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


def _require_reviewer(me: AppUser, run: AssessmentRun, action: str) -> None:
    if not svc.can_review(me, run):
        raise HTTPException(403, f"Only the person who started this assessment or an admin can {action}")


# ---------- domain workspace ----------


async def _ensure_first_question(db: TenantDB, run: AssessmentRun, rd: RunDomain) -> None:
    """The first time a domain is opened, its first question is added to the conversation."""
    if run.status not in ("in_progress", "changes_requested"):
        return
    started = select(ConversationMessage.id).join(Conversation, Conversation.id == ConversationMessage.conversation_id).where(
        Conversation.run_domain_id == rd.id).limit(1)
    if (await db.execute(started)).first():
        return
    # Locked so two page loads at the same moment don't both add it. If someone else holds the lock
    # (another page load, or a chat turn), they are taking care of it: don't wait.
    conv = (await db.execute(select(Conversation).where(Conversation.run_domain_id == rd.id)
                             .with_for_update(skip_locked=True))).scalar_one_or_none()
    if conv is not None and not (await db.execute(started)).first():
        q = await svc.current_question(db, rd)
        if q:
            db.add(ConversationMessage(conversation_id=conv.id, role="system_event", content=q.text,
                                       data={"kind": "question", "run_question_id": str(q.id), "follow_up": False}))
    await db.commit()  # also releases the lock


@router.get("/{run_id}/domains/{run_domain_id}", response_model=Workspace)
async def workspace(run_id: uuid.UUID, run_domain_id: uuid.UUID, db: TenantDB, me: TenantMember) -> Workspace:
    run = await svc.get_run(db, me, run_id)
    rd = await svc.get_domain(db, run, run_domain_id)
    unread = (await db.execute(select(Evidence.id).where(
        Evidence.run_id == run.id, Evidence.processing_status.in_(("pending", "processing"))))).scalars().all()
    await jobs.expire_stale(db, run.id, *unread)  # jobs that can no longer finish must not leave the page waiting
    await _ensure_first_question(db, run, rd)
    scope = await svc.load_run_scope(db, run.assessment_version_id)
    evals = await svc.evaluations_by_req(db, run.id)

    from app.models import Question  # local import keeps the module header short

    qs = (await db.execute(select(RunQuestion).where(RunQuestion.run_domain_id == rd.id)
                           .order_by(RunQuestion.sort_order, RunQuestion.created_at))).scalars().all()
    answers = dict((await db.execute(select(Response.run_question_id, Response.answer_text).where(Response.run_id == run.id))).all())
    help_texts = dict((await db.execute(select(Question.id, Question.help_text).where(
        Question.id.in_([q.question_id for q in qs if q.question_id])))).all()) if qs else {}
    questions = []
    for q in qs:
        reqs = await svc.question_requirements(db, scope, q)
        questions.append(QuestionState(
            id=q.id, kind=q.kind, parent_id=q.parent_run_question_id, text=q.text, help_text=help_texts.get(q.question_id),
            status=q.status, proposed_na=q.proposed_na, proposed_na_reason=q.proposed_na_reason,
            requirement_keys=[scope.by_id[r].key for r in reqs], answer=answers.get(q.id)))

    ev_files = (await db.execute(select(Evidence).where(Evidence.run_id == run.id).order_by(Evidence.created_at))).scalars().all()
    names = {e.id: e.filename for e in ev_files}
    domain_req_ids = [r.id for r in scope.reqs_for_domain(rd.assessment_version_domain_id)]
    clause_map: dict[uuid.UUID, list[dict]] = {}
    for rv_id, ref, title, fw in (await db.execute(
            select(RequirementClauseMap.requirement_version_id, FrameworkClause.ref, FrameworkClause.title, Framework.code)
            .join(FrameworkClause, FrameworkClause.id == RequirementClauseMap.framework_clause_id)
            .join(FrameworkVersion, FrameworkVersion.id == FrameworkClause.framework_version_id)
            .join(Framework, Framework.id == FrameworkVersion.framework_id)
            .where(RequirementClauseMap.requirement_version_id.in_(domain_req_ids)))).all():
        clause_map.setdefault(rv_id, []).append({"framework_code": fw, "ref": ref, "title": title})
    reqs_out = []
    for r in scope.reqs_for_domain(rd.assessment_version_domain_id):
        e = evals.get(r.id)
        ev_out = None
        if e:
            cites = (await db.execute(select(EvaluationCitation).where(EvaluationCitation.evaluation_id == e.id))).scalars().all()
            ev_out = EvaluationOut(
                id=e.id, rating=e.rating, is_na=e.is_na, na_reason=e.na_reason, rationale=e.rationale, ai_rating=e.ai_rating,
                ai_is_na=e.ai_is_na, status=e.status, verified_by=await _person(db, e.verified_by), answer=e.answer,
                citations=[Citation(evidence_id=c.evidence_id, evidence_filename=names.get(c.evidence_id), response_id=c.response_id,
                                    excerpt=c.excerpt) for c in cites if c.evidence_id])
        reqs_out.append(RequirementState(id=r.id, key=r.key, control=r.control, statement=r.statement, guidance=r.guidance, evidence=r.evidence, mandatory=r.mandatory,
                                         clauses=clause_map.get(r.id, []), evaluation=ev_out))

    conv = (await db.execute(select(Conversation).where(Conversation.run_domain_id == rd.id))).scalar_one()
    msgs = (await db.execute(select(ConversationMessage).where(ConversationMessage.conversation_id == conv.id)
                             .order_by(ConversationMessage.created_at))).scalars().all()
    authors = {m.author_id for m in msgs if m.author_id}
    people = {uid: await _person(db, uid) for uid in authors}
    comments = (await db.execute(select(ReviewComment).where(ReviewComment.run_domain_id == rd.id).order_by(ReviewComment.created_at))).scalars().all()
    current = await svc.current_question(db, rd)
    summary = await _domain_summary(db, run, rd, scope, evals, me)
    return Workspace(
        run_id=run.id, run_status=run.status, domain=summary, current_question_id=current.id if current else None,
        questions=questions, requirements=reqs_out,
        messages=[MessageOut(id=m.id, role=m.role, content=m.content, data=m.data, author=people.get(m.author_id), created_at=m.created_at) for m in msgs],
        evidence=[EvidenceOut(id=e.id, filename=e.filename, content_type=e.content_type, size_bytes=e.size_bytes, processing_status=e.processing_status,
                              summary=e.summary, uploaded_by=e.uploaded_by, created_at=e.created_at) for e in ev_files],
        comments=[{"id": str(c.id), "comment": c.comment, "created_at": c.created_at.isoformat(), "resolved": c.resolved_at is not None,
                   "author": (await _person(db, c.created_by)).full_name} for c in comments],
        editable=summary.can_work and run.status in ("in_progress", "changes_requested") and rd.status != "completed",
        ai_paused=await _ai_paused(db, run),
        analysis_pending=(await db.execute(select(Job.id).where(
            Job.ref_id == run.id, Job.type == "cross_analyze", Job.status.in_(("queued", "running"))).limit(1))).first() is not None,
    )


async def _editable_domain(db: TenantDB, me: AppUser, run_id: uuid.UUID, run_domain_id: uuid.UUID) -> tuple[AssessmentRun, RunDomain]:
    run = await svc.get_run(db, me, run_id)
    rd = await svc.get_domain(db, run, run_domain_id)
    if not svc.can_work_on(me, run, rd):
        raise HTTPException(403, "This domain is assigned to someone else")
    svc.require_editable(run, rd)
    return run, rd


@router.post("/{run_id}/domains/{run_domain_id}/messages", response_model=Workspace)
async def send_message(run_id: uuid.UUID, run_domain_id: uuid.UUID, body: MessageIn, db: TenantDB, me: TenantMember) -> Workspace:
    run, rd, evidence = await _turn_inputs(db, me, run_id, run_domain_id, body)
    turn = guide.Turn(db, run, rd, me)
    try:
        await turn.run_turn(body.content.strip(), evidence)
    except ai.AIError as e:
        await db.rollback()
        raise HTTPException(502, str(e)) from e
    await db.commit()
    await _queue_cross(db, run, turn.cross_payloads)
    return await workspace(run_id, run_domain_id, db, me)


async def _queue_cross(db: TenantDB, run: AssessmentRun, payloads: list[dict]) -> None:
    """Analyse submitted answers/evidence against every open requirement in the assessment, in the background."""
    for payload in payloads:
        if (payload.get("text") or "").strip() or payload.get("evidence_ids"):
            await enqueue(db, type="cross_analyze", ref_type="assessment_run", ref_id=run.id, payload=payload)


async def _turn_inputs(db: TenantDB, me: AppUser, run_id: uuid.UUID, run_domain_id: uuid.UUID, body: MessageIn):
    run, rd = await _editable_domain(db, me, run_id, run_domain_id)
    if not body.content.strip() and not body.evidence_ids:
        raise HTTPException(422, "Write a message or attach evidence")
    if reason := await guide.turn_block_reason(db, run, rd):
        raise HTTPException(409, reason)
    evidence = []
    for eid in body.evidence_ids:
        ev = await db.get(Evidence, eid)
        if ev is None or ev.run_id != run.id:
            raise HTTPException(422, "Unknown evidence")
        if ev.processing_status != "ready":
            raise HTTPException(409, f"{ev.filename} is still being processed")
        evidence.append(ev)
    return run, rd, evidence


@router.post("/{run_id}/domains/{run_domain_id}/messages/stream")
async def stream_message(run_id: uuid.UUID, run_domain_id: uuid.UUID, body: MessageIn, db: TenantDB, me: TenantMember) -> StreamingResponse:
    """Server-Sent Events: `text` deltas and `status` updates while the guide works, then `done`
    (refetch the workspace) or `error`. Nothing is saved unless the whole turn succeeds."""
    await _turn_inputs(db, me, run_id, run_domain_id, body)  # validate before opening the stream
    user_id, tenant_id = me.id, tenant_of(db)
    # The request's session would otherwise hold a connection, idle, until the stream ends.
    await db.close()

    async def events():
        def sse(payload: dict) -> str:
            return f"data: {json.dumps(payload)}\n\n"

        # The turn runs in its own session, which lives as long as the stream.
        async with session_for(tenant_id) as session:
            try:
                user = await session.get(AppUser, user_id)
                run, rd, evidence = await _turn_inputs(session, user, run_id, run_domain_id, body)
                turn = guide.Turn(session, run, rd, user)
                async for event in turn.stream_turn(body.content.strip(), evidence):
                    yield sse(event)
                await session.commit()
                await _queue_cross(session, run, turn.cross_payloads)
                yield sse({"type": "done"})
            except (ai.AIError, HTTPException) as e:
                await session.rollback()
                yield sse({"type": "error", "message": str(e.detail if isinstance(e, HTTPException) else e)})
            except Exception:  # noqa: BLE001 - report, never leave the client hanging
                await session.rollback()
                logging.getLogger("guide").exception("streamed turn failed")
                yield sse({"type": "error", "message": "Something went wrong. Please try again."})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"cache-control": "no-cache", "x-accel-buffering": "no"})


@router.post("/{run_id}/questions/{run_question_id}/na", response_model=Workspace)
async def confirm_na(run_id: uuid.UUID, run_question_id: uuid.UUID, body: NaIn, db: TenantDB, me: TenantMember) -> Workspace:
    """The user confirms a question doesn't apply: its requirements become N/A (verified by them)."""
    run = await svc.get_run(db, me, run_id)
    rq = await db.get(RunQuestion, run_question_id)
    if rq is None or rq.run_id != run.id:
        raise HTTPException(404, "Question not found")
    run, rd = await _editable_domain(db, me, run_id, rq.run_domain_id)
    current = await svc.current_question(db, rd)
    if current is None or current.id != rq.id:
        raise HTTPException(409, "Only the current question can be marked as not applicable")
    turn = guide.Turn(db, run, rd, me)
    await turn.setup()
    scope = turn.scope
    for rid in await svc.question_requirements(db, scope, rq):
        ev = (await svc.evaluations_by_req(db, run.id)).get(rid)
        if ev is None:
            ev = RequirementEvaluation(run_id=run.id, requirement_version_id=rid, rationale="")
            db.add(ev)
        ev.rating, ev.is_na, ev.na_reason, ev.ai_rating, ev.ai_is_na = None, True, body.reason, None, True
        ev.rationale = f"Marked not applicable by {me.full_name}: {body.reason}"
        ev.status, ev.verified_by, ev.verified_at = "verified", me.id, svc.now()
    await turn._save_response(rq, f"Not applicable: {body.reason}", True, body.reason)
    rq.status = "skipped_na"
    if rd.status == "not_started":
        rd.status = "in_progress"
    await turn._ui("system_event", "Marked not applicable", {"kind": "answer_saved", "run_question_id": str(rq.id), "not_applicable": True})
    turn.state["pending_evidence"], turn.state["rated_this_question"] = [], []
    await turn._announce_next("")  # the model sees the new current question in its next turn context
    turn.save_state()
    await db.commit()
    return await workspace(run_id, rd.id, db, me)


@router.put("/{run_id}/evaluations/{evaluation_id}", response_model=Workspace)
async def verify(run_id: uuid.UUID, evaluation_id: uuid.UUID, body: EvaluationIn, db: TenantDB, me: TenantMember) -> Workspace:
    run = await svc.get_run(db, me, run_id)
    ev = await db.get(RequirementEvaluation, evaluation_id)
    if ev is None or ev.run_id != run.id:
        raise HTTPException(404, "Rating not found")
    scope = await svc.load_run_scope(db, run.assessment_version_id)
    avd = scope.domain_of[ev.requirement_version_id]
    rd = (await db.execute(select(RunDomain).where(RunDomain.run_id == run.id, RunDomain.assessment_version_domain_id == avd))).scalar_one()
    if not svc.can_work_on(me, run, rd):
        raise HTTPException(403, "This domain is assigned to someone else")
    svc.require_editable(run, rd)
    if body.is_na and not (body.na_reason or "").strip():
        raise HTTPException(422, "A reason is required for not applicable")
    if not body.is_na and body.rating is None:
        raise HTTPException(422, "Choose a rating")
    ev.is_na, ev.rating, ev.na_reason = body.is_na, None if body.is_na else body.rating, body.na_reason if body.is_na else None
    same = ev.is_na == bool(ev.ai_is_na) and (ev.is_na or ev.rating == ev.ai_rating)
    ev.status = "verified" if same else "overridden"
    ev.verified_by, ev.verified_at = me.id, svc.now()
    await db.commit()
    return await workspace(run_id, rd.id, db, me)


class RequirementIn(BaseModel):
    answer: str | None = Field(default=None, max_length=4000)
    rating: int | None = Field(default=None, ge=0, le=4)
    is_na: bool = False
    na_reason: str | None = Field(default=None, max_length=2000)
    evidence_ids: list[uuid.UUID] = Field(default=[], max_length=20)


@router.put("/{run_id}/requirements/{requirement_version_id}", response_model=Workspace)
async def save_requirement(run_id: uuid.UUID, requirement_version_id: uuid.UUID, body: RequirementIn, db: TenantDB, me: TenantMember) -> Workspace:
    """A person answers, rates and/or attaches evidence for one requirement, at any time.

    With a rating (or N/A) the requirement is completed by that person. With only an answer and/or
    evidence it becomes `awaiting_ai`, and the background analysis suggests a rating. Either way, the
    answer and evidence are then checked against every other open requirement in the assessment."""
    run = await svc.get_run(db, me, run_id)
    scope = await svc.load_run_scope(db, run.assessment_version_id)
    avd = scope.domain_of.get(requirement_version_id)
    if avd is None:
        raise HTTPException(404, "Requirement not found")
    rd = (await db.execute(select(RunDomain).where(RunDomain.run_id == run.id, RunDomain.assessment_version_domain_id == avd))).scalar_one()
    if not svc.can_work_on(me, run, rd):
        raise HTTPException(403, "This domain is assigned to someone else")
    svc.require_editable(run, rd)

    answer = (body.answer or "").strip() or None
    has_rating = body.is_na or body.rating is not None
    if body.is_na and not (body.na_reason or "").strip():
        raise HTTPException(422, "A reason is required for not applicable")
    evidence = []
    for eid in dict.fromkeys(body.evidence_ids):
        ev = await db.get(Evidence, eid)
        if ev is None or ev.run_id != run.id:
            raise HTTPException(422, "Unknown evidence")
        evidence.append(ev)
    if not has_rating and not answer and not evidence:
        raise HTTPException(422, "Choose a rating, or add an answer or evidence for the AI to rate")
    if not has_rating and await _ai_paused(db, run):
        raise HTTPException(409, "AI assistance for this assessment has reached its limit. Choose a rating yourself.")

    ev_row = (await svc.evaluations_by_req(db, run.id)).get(requirement_version_id)
    if ev_row is None:
        ev_row = RequirementEvaluation(run_id=run.id, requirement_version_id=requirement_version_id, rationale="")
        db.add(ev_row)
    previous_answer = ev_row.answer
    ev_row.answer = answer
    if has_rating:
        ev_row.is_na, ev_row.rating = body.is_na, None if body.is_na else body.rating
        ev_row.na_reason = body.na_reason.strip() if body.is_na else None
        has_ai = ev_row.ai_rating is not None or bool(ev_row.ai_is_na)
        same = has_ai and ev_row.is_na == bool(ev_row.ai_is_na) and (ev_row.is_na or ev_row.rating == ev_row.ai_rating)
        ev_row.status = "verified" if same else "overridden"
        if not has_ai or not ev_row.rationale:
            ev_row.rationale = f"Rated by {me.full_name}."
        ev_row.verified_by, ev_row.verified_at = me.id, svc.now()
    elif ev_row.status not in ("ai_suggested",) or answer != previous_answer or evidence:
        # New information without a rating: let the AI (re)rate it.
        ev_row.rating, ev_row.is_na, ev_row.na_reason, ev_row.status = None, False, None, "awaiting_ai"
        ev_row.rationale = "Waiting for the AI to rate this from your answer and evidence."
        ev_row.verified_by, ev_row.verified_at = None, None
    await db.flush()
    for ev in evidence:
        exists = (await db.execute(select(EvaluationCitation.id).where(
            EvaluationCitation.evaluation_id == ev_row.id, EvaluationCitation.evidence_id == ev.id))).first()
        if not exists:
            db.add(EvaluationCitation(evaluation_id=ev_row.id, evidence_id=ev.id, excerpt=None))
    if rd.status == "not_started":
        rd.status = "in_progress"
    await db.commit()

    new_info = (answer and answer != previous_answer) or evidence
    if new_info and not await _ai_paused(db, run):
        await _queue_cross(db, run, [{
            "source": "requirement", "text": answer, "evidence_ids": [str(e.id) for e in evidence],
            "target_requirement_version_id": None if has_rating else str(requirement_version_id),
        }])
    return await workspace(run_id, rd.id, db, me)


@router.post("/{run_id}/domains/{run_domain_id}/complete", response_model=RunDetail)
async def complete_domain(run_id: uuid.UUID, run_domain_id: uuid.UUID, db: TenantDB, me: TenantMember) -> RunDetail:
    run, rd = await _editable_domain(db, me, run_id, run_domain_id)
    scope = await svc.load_run_scope(db, run.assessment_version_id)
    evals = await svc.evaluations_by_req(db, run.id)
    pending = [r.key for r in scope.reqs_for_domain(rd.assessment_version_domain_id)
               if r.id not in evals or evals[r.id].status in ("ai_suggested", "awaiting_ai")]
    if pending:
        raise HTTPException(409, f"Rate and confirm every requirement first ({len(pending)} left: {', '.join(pending[:6])}{'…' if len(pending) > 6 else ''})")
    # Every requirement has a confirmed rating, so any question still open (for example while AI
    # assistance is paused) has served its purpose: close it.
    while (open_q := await svc.current_question(db, rd)) is not None:
        open_q.status = "answered"
        await db.flush()
    rd.status, rd.completed_by, rd.completed_at = "completed", me.id, svc.now()
    for c in (await db.execute(select(ReviewComment).where(ReviewComment.run_domain_id == rd.id, ReviewComment.resolved_at.is_(None)))).scalars():
        c.resolved_by, c.resolved_at = me.id, svc.now()
    await db.commit()
    return await get_run(run_id, db, me)


@router.post("/{run_id}/domains/{run_domain_id}/reopen", response_model=RunDetail)
async def reopen_domain(run_id: uuid.UUID, run_domain_id: uuid.UUID, db: TenantDB, me: TenantMember) -> RunDetail:
    run = await svc.get_run(db, me, run_id)
    rd = await svc.get_domain(db, run, run_domain_id)
    if not svc.can_work_on(me, run, rd):
        raise HTTPException(403, "This domain is assigned to someone else")
    if run.status not in ("in_progress", "changes_requested") or rd.status != "completed":
        raise HTTPException(409, "This domain can't be reopened now")
    rd.status = "in_progress"
    await db.commit()
    return await get_run(run_id, db, me)


# ---------- evidence ----------


@router.post("/{run_id}/evidence", response_model=EvidenceOut, status_code=201)
async def upload_evidence(run_id: uuid.UUID, db: TenantDB, me: TenantMember, file: UploadFile = File(...)) -> EvidenceOut:
    run = await svc.get_run(db, me, run_id)
    svc.require_editable(run)
    domains = (await db.execute(select(RunDomain).where(RunDomain.run_id == run.id))).scalars().all()
    if not any(svc.can_work_on(me, run, rd) for rd in domains):
        raise HTTPException(403, "Every domain of this assessment is assigned to someone else")
    if await _ai_paused(db, run):
        raise HTTPException(409, "AI assistance for this assessment has reached its limit, so new evidence can't be read")
    filename = clean_filename(file.filename, "evidence")
    ctype = guess_type(filename, file.content_type)
    if ctype not in ALLOWED:
        raise HTTPException(422, "Upload a PDF, Word, Excel, CSV, text, PNG or JPG file")
    data = await read_limited(file, MAX_EVIDENCE, "Files can be up to 25 MB")
    if not looks_like(data, ctype):
        raise HTTPException(422, f"{filename} doesn't look like a {filename.rsplit('.', 1)[-1].upper()} file")
    digest = hashlib.sha256(data).hexdigest()
    ev = (await db.execute(select(Evidence).where(Evidence.run_id == run.id, Evidence.sha256 == digest))).scalar_one_or_none()
    if ev is None:  # the same file is stored and processed only once per run
        ev = Evidence(run_id=run.id, storage_key="", filename=filename,
                      content_type=ctype, size_bytes=len(data), sha256=digest, uploaded_by=me.id)
        db.add(ev)
        await db.flush()
        # The key never contains the file name: names are user input.
        ev.storage_key = f"tenants/{tenant_of(db)}/runs/{run.id}/evidence/{ev.id}"
        await asyncio.to_thread(put_object, ev.storage_key, data, ctype)
        await enqueue(db, type="process_evidence", ref_type="evidence", ref_id=ev.id)
    elif ev.processing_status == "failed":
        # Uploading the same file again is how a file that couldn't be read is retried.
        ev.processing_status, ev.processing_error = "pending", None
        await enqueue(db, type="process_evidence", ref_type="evidence", ref_id=ev.id)
    else:
        await db.commit()
    return EvidenceOut(id=ev.id, filename=ev.filename, content_type=ev.content_type, size_bytes=ev.size_bytes,
                       processing_status=ev.processing_status, summary=ev.summary, uploaded_by=ev.uploaded_by, created_at=ev.created_at)


@router.get("/{run_id}/evidence/{evidence_id}/file")
async def download_evidence(run_id: uuid.UUID, evidence_id: uuid.UUID, db: TenantDB, me: TenantMember) -> RawResponse:
    run = await svc.get_run(db, me, run_id)
    ev = await db.get(Evidence, evidence_id)
    if ev is None or ev.run_id != run.id:
        raise HTTPException(404, "File not found")
    data = await asyncio.to_thread(get_object, ev.storage_key)
    # Only PDFs and images open in the browser; everything else downloads. The type is never guessed.
    inline = ev.content_type == PDF or ev.content_type in IMAGES
    return RawResponse(data, media_type=ev.content_type, headers={
        "content-disposition": content_disposition(ev.filename, inline=inline), "x-content-type-options": "nosniff"})


# ---------- submission, review, results ----------


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


class ItemOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    status: str
    requirement_keys: list[str]


class ActionOut(ItemOut):
    priority: str | None
    owner: Person | None
    due_date: str | None


class RiskOut(ItemOut):
    category: str | None
    likelihood: int
    impact: int
    score: int
    treatment: str | None
    owner: Person | None


class Results(BaseModel):
    report: dict | None
    report_status: str | None
    actions: list[ActionOut]
    risks: list[RiskOut]


async def _keys(db: TenantDB, scope: svc.RunScope, model, fk: str, item_id: uuid.UUID) -> list[str]:
    rows = (await db.execute(select(model.requirement_version_id).where(getattr(model, fk) == item_id))).scalars().all()
    return [scope.by_id[r].key for r in rows if r in scope.by_id]


async def action_out(db: TenantDB, scope: svc.RunScope | None, a: ActionItem) -> ActionOut:
    return ActionOut(id=a.id, title=a.title, description=a.description, status=a.status, priority=a.priority,
                     owner=await _person(db, a.owner_id), due_date=a.due_date.isoformat() if a.due_date else None,
                     requirement_keys=await _keys(db, scope, ActionItemRequirement, "action_item_id", a.id) if scope else [])


async def risk_out(db: TenantDB, scope: svc.RunScope | None, r: Risk) -> RiskOut:
    return RiskOut(id=r.id, title=r.title, description=r.description, status=r.status, category=r.category,
                   likelihood=r.likelihood, impact=r.impact, score=r.likelihood * r.impact, treatment=r.treatment,
                   owner=await _person(db, r.owner_id),
                   requirement_keys=await _keys(db, scope, RiskRequirement, "risk_id", r.id) if scope else [])


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
