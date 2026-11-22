"""Background cross-analysis: when someone submits an answer or evidence (in the chat or on a single
requirement), check whether it also supports other requirements across the whole assessment that
are not completed yet, and save AI suggestions for them.

Never touches a requirement a person has rated or confirmed (verified / overridden).
"""

import logging
import uuid

import ai_contracts as contracts
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import tenant_of
from app.models import AssessmentRun, EvaluationCitation, Evidence, RequirementEvaluation
from app.services import ai
from app.services.runs import company_contract, evaluations_by_req, load_run_scope

log = logging.getLogger("cross_analysis")
OPEN_STATUSES = (None, "awaiting_ai", "ai_suggested")  # None = no rating yet


class EvidenceNotReady(Exception):
    """Evidence is still being read; the job should be retried shortly."""


async def analyze(db: AsyncSession, run_id: uuid.UUID, payload: dict) -> dict:
    """payload: {"source": "chat"|"requirement", "text": str|None, "evidence_ids": [...],
    "target_requirement_version_id": str|None, "author": str|None}"""
    run = await db.get(AssessmentRun, run_id)
    if await ai.run_spend(db, run.id) >= get_settings().run_ai_budget_usd:
        return {"skipped": "AI budget for this assessment is used up"}

    evidence: list[Evidence] = []
    for eid in payload.get("evidence_ids") or []:
        ev = await db.get(Evidence, uuid.UUID(eid))
        if ev is None or ev.run_id != run.id:
            continue
        if ev.processing_status in ("pending", "processing"):
            raise EvidenceNotReady(ev.filename)
        if ev.processing_status == "ready":
            evidence.append(ev)
    text = (payload.get("text") or "").strip()
    if not text and not evidence:
        return {"skipped": "nothing to analyse"}

    scope = await load_run_scope(db, run.assessment_version_id)
    evals = await evaluations_by_req(db, run.id)
    target = payload.get("target_requirement_version_id")

    def is_open(r) -> bool:
        e = evals.get(r.id)
        return (e.status if e else None) in OPEN_STATUSES

    open_reqs = [(r, evals.get(r.id)) for d in scope.domains for r in d.requirements if is_open(r)]
    if not open_reqs:
        return {"skipped": "every requirement is already completed"}

    def open_requirement(r) -> contracts.OpenRequirement:
        e = evals.get(r.id)
        existing = None
        if e and e.status == "ai_suggested":
            existing = contracts.ExistingSuggestion(rating=e.rating, is_na=e.is_na, rationale=e.rationale or "")
        return contracts.OpenRequirement(key=r.key, statement=r.statement, guidance=r.guidance or "", evidence=list(r.evidence),
                                         target=bool(target and str(r.id) == target), existing=existing)

    domains = []
    for d in scope.domains:
        controls = [contracts.OpenControl(context=ctx.contract(), requirements=[open_requirement(r) for r in reqs])
                    for ctx, reqs in d.by_control(keep=is_open)]
        if controls:
            domains.append(contracts.OpenDomain(name=d.name, controls=controls))

    result = await ai.call(
        "/cross-analysis",
        contracts.CrossAnalysisIn(
            company=await company_contract(db, run), domains=domains,
            source="requirement" if payload.get("source") == "requirement" else "chat", text=text or None,
            evidence=[contracts.EvidenceFile(id=str(ev.id), filename=ev.filename, summary=ev.summary, text=ev.extracted_text)
                      for ev in evidence]),
        contracts.CrossResult, ai.UsageTag("cross_analysis", tenant_of(db), run.id))

    valid_evidence = {str(ev.id) for ev in evidence}
    by_key = {r.key: (r, e) for r, e in open_reqs}
    updated = []
    fresh = await evaluations_by_req(db, run.id)  # re-read: a person may have rated meanwhile
    for item in result.ratings:
        if item.requirement not in by_key:
            continue
        req, _ = by_key[item.requirement]
        ev_row = fresh.get(req.id)
        if ev_row and ev_row.status in ("verified", "overridden"):
            continue
        na = bool(item.not_applicable)
        rating = None if na else item.rating
        if (not na and (rating is None or not 0 <= rating <= 4)) or (na and not (item.na_reason or "").strip()):
            continue
        if ev_row is None:
            ev_row = RequirementEvaluation(run_id=run.id, requirement_version_id=req.id, rationale="")
            db.add(ev_row)
        ev_row.rating, ev_row.is_na, ev_row.na_reason = rating, na, (item.na_reason if na else None)
        ev_row.ai_rating, ev_row.ai_is_na, ev_row.rationale, ev_row.status = rating, na, item.rationale, "ai_suggested"
        await db.flush()
        for eid in item.evidence_ids:
            if eid in valid_evidence:
                exists = (await db.execute(select(EvaluationCitation.id).where(
                    EvaluationCitation.evaluation_id == ev_row.id, EvaluationCitation.evidence_id == uuid.UUID(eid)))).first()
                if not exists:
                    db.add(EvaluationCitation(evaluation_id=ev_row.id, evidence_id=uuid.UUID(eid), excerpt=item.quote))
        updated.append(item.requirement)

    # A target the model didn't rate must not stay "awaiting" forever.
    if target:
        tgt = fresh.get(uuid.UUID(target))
        if tgt and tgt.status == "awaiting_ai":
            tgt.rating, tgt.is_na, tgt.status = 0, False, "ai_suggested"
            tgt.ai_rating, tgt.ai_is_na = 0, False
            tgt.rationale = "The information provided wasn't enough to rate this requirement. Add more detail or rate it yourself."
    await db.flush()
    log.info("cross-analysis run=%s updated=%s", run.id, updated)
    return {"updated": updated}
