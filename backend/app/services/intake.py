"""Pre-assessment intake: the AI service writes a few context questions from the controls in
scope, then tailors the run's questions (wording, order, proposed N/A) from the answers.

Tailoring can never add or remove questions; proposed N/A is only a suggestion the user confirms."""

import uuid

import ai_contracts as contracts
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import tenant_of
from app.models import AssessmentRun, RunDomain, RunQuestion
from app.services import ai
from app.services.runs import company_contract, load_run_scope


async def generate_intake(db: AsyncSession, run_id: uuid.UUID) -> dict:
    run = await db.get(AssessmentRun, run_id)
    scope = await load_run_scope(db, run.assessment_version_id)
    result = await ai.call(
        "/intake/questions",
        contracts.IntakeIn(company=await company_contract(db), domains=[d.contract() for d in scope.domains]),
        contracts.IntakeQuestions, ai.UsageTag("intake", tenant_of(db), run.id))
    run.intake_summary = {"status": "ready", "questions": [q.model_dump() for q in result.questions], "answers": {}}
    await db.flush()
    return {"questions": len(result.questions)}


async def tailor(db: AsyncSession, run_id: uuid.UUID) -> dict:
    run = await db.get(AssessmentRun, run_id)
    intake = dict(run.intake_summary or {})
    answers = [contracts.IntakeAnswer(question=q["text"], answer=intake.get("answers", {}).get(q["id"]) or None)
               for q in intake.get("questions", [])]

    domains = (await db.execute(select(RunDomain).where(RunDomain.run_id == run.id))).scalars().all()
    scope = await load_run_scope(db, run.assessment_version_id)
    name_of = {d.avd_id: d.name for d in scope.domains}
    keyed: dict[str, RunQuestion] = {}
    tailor_domains = []
    n = 0
    for rd in sorted(domains, key=lambda x: [d.avd_id for d in scope.domains].index(x.assessment_version_domain_id)):
        qs = (await db.execute(select(RunQuestion).where(RunQuestion.run_domain_id == rd.id, RunQuestion.kind == "base")
                               .order_by(RunQuestion.sort_order))).scalars().all()
        questions = []
        for q in qs:
            n += 1
            keyed[f"Q{n}"] = q
            questions.append(contracts.KeyedQuestion(key=f"Q{n}", text=q.text))
        tailor_domains.append(contracts.TailorDomainIn(name=name_of[rd.assessment_version_domain_id], questions=questions))

    result = await ai.call(
        "/intake/tailor",
        contracts.TailorIn(company=await company_contract(db), intake=answers, domains=tailor_domains),
        contracts.Tailoring, ai.UsageTag("tailoring", tenant_of(db), run.id))

    for tq in result.questions:
        q = keyed.get(tq.key)
        if q is None:
            continue
        if tq.text.strip():
            q.text = tq.text.strip()
        q.proposed_na = bool(tq.propose_na and tq.na_reason)
        q.proposed_na_reason = tq.na_reason if q.proposed_na else None
    # Apply order only when a domain's ordering is a permutation of its own questions.
    for td in result.domains:
        own = {k for k, q in keyed.items() if name_of.get(_domain_avd(domains, q.run_domain_id)) == td.domain}
        if set(td.question_keys_in_order) == own and len(td.question_keys_in_order) == len(own):
            for i, k in enumerate(td.question_keys_in_order):
                keyed[k].sort_order = i * 10

    intake["context_summary"] = result.context_summary
    intake["status"] = "tailored"
    run.intake_summary = intake
    run.status = "in_progress"
    await db.flush()
    return {"tailored": len(result.questions), "proposed_na": sum(1 for q in keyed.values() if q.proposed_na)}


def _domain_avd(domains: list[RunDomain], run_domain_id: uuid.UUID) -> uuid.UUID | None:
    return next((d.assessment_version_domain_id for d in domains if d.id == run_domain_id), None)
