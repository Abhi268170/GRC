"""Working on one domain of a run: the workspace, the guided chat, ratings, completing and reopening."""

import json
import logging
import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from app.core.auth import TenantDB, TenantMember
from app.core.db import session_for, tenant_of
from app.core.queue import enqueue
from app.models import (
    AppUser,
    AssessmentRun,
    Conversation,
    ConversationMessage,
    EvaluationCitation,
    Evidence,
    Framework,
    FrameworkClause,
    FrameworkVersion,
    Job,
    RequirementClauseMap,
    RequirementEvaluation,
    Response,
    ReviewComment,
    RunDomain,
    RunQuestion,
)
from app.services import ai, guide, jobs
from app.services import runs as svc
from app.api.runs.lifecycle import get_run
from app.api.runs.schemas import Citation, EvaluationIn, EvaluationOut, EvidenceOut, MessageIn, MessageOut, NaIn, QuestionState, RequirementIn, RequirementState, RunDetail, Workspace
from app.api.runs.views import _ai_paused, _domain_summary, _person

router = APIRouter(prefix="/runs", tags=["runs"])


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
