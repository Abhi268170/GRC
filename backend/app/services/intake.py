"""Pre-assessment intake: AI writes a few context questions from the controls in scope,
then tailors the run's questions (wording, order, proposed N/A) from the answers.

Tailoring can never add or remove questions; proposed N/A is only a suggestion the user confirms."""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import tenant_of
from app.models import AssessmentRun, RunDomain, RunQuestion
from app.services import ai
from app.services.runs import company, load_run_scope


class IntakeQuestion(BaseModel):
    id: str = Field(description="Short id like i1, i2.")
    text: str = Field(description="A short, plain-English question.")
    hint: str | None = Field(description="Optional example answer or clarification.")
    options: list[str] = Field(description="Suggested quick answers (2-5) when the answer is usually one of a few options; empty for free text.")


class IntakeQuestions(BaseModel):
    questions: list[IntakeQuestion]


class TailoredQuestion(BaseModel):
    key: str = Field(description="The question key you were given, e.g. Q3.")
    text: str = Field(description="The question reworded for this company. Keep its meaning and everything it asks about.")
    propose_na: bool = Field(description="True only if the intake answers make it very likely the whole question doesn't apply.")
    na_reason: str | None = Field(description="Why it likely doesn't apply, in one sentence. Null if propose_na is false.")


class TailoredDomain(BaseModel):
    domain: str = Field(description="The domain name exactly as given.")
    question_keys_in_order: list[str] = Field(description="Every question key of this domain, in the order to ask them.")


class Tailoring(BaseModel):
    context_summary: str = Field(description="Three to five sentences summarising the company's context relevant to this assessment.")
    questions: list[TailoredQuestion]
    domains: list[TailoredDomain]


INTAKE_SYSTEM = """You prepare a short pre-assessment intake for a security and compliance assessment.

Write 4 to 6 quick questions that capture the company context needed to tailor the assessment: for example which systems and data are in scope, where things are hosted, team structure, and existing tools or certifications. Choose questions based on the controls in scope; skip anything the company profile already answers.

Keep them easy for a non-expert to answer in a few words. Offer quick-answer options when an answer is usually one of a few choices."""

TAILOR_SYSTEM = """You tailor an assessment's questions to a specific company using its intake answers.

For each question:
- Reword it to fit the company (use their terminology, systems and examples) while keeping exactly what it asks about. Don't drop any part of the question.
- Propose N/A only when the intake answers make it very likely that the entire question does not apply. Be conservative; the user confirms any N/A.

Also order the questions within each domain so the conversation flows naturally, and summarise the company context. Return every question key exactly once; never add or remove questions."""


async def generate_intake(db: AsyncSession, run_id: uuid.UUID) -> dict:
    run = await db.get(AssessmentRun, run_id)
    tenant = await company(db)
    scope = await load_run_scope(db, run.assessment_version_id)
    controls = []
    for d in scope.domains:
        controls.append(f"\n## {d.name}")
        seen: list = []
        for r in d.requirements:
            if r.control_version_id not in seen:
                seen.append(r.control_version_id)
                ctx = d.controls.get(r.control_version_id)
                controls.append(ctx.render("brief") if ctx else f"Control: {r.control}")
    # The brief control context includes what each control applies to (use cases) and the events that call
    # for it (triggers): the intake asks about exactly these, so the questions can be tailored.
    prompt = (f"Company: {tenant.name}\nIndustry: {tenant.industry}\nEmployees: {tenant.employee_count}\n\n"
              "Controls in scope by domain:" + "\n".join(controls))
    result = await ai.structured(output=IntakeQuestions, system=INTAKE_SYSTEM, content=prompt,
                                 model=ai.conversation_model(), effort="low", max_tokens=8000,
                                 usage=ai.UsageTag("intake", tenant_of(db), run.id))
    run.intake_summary = {"status": "ready", "questions": [q.model_dump() for q in result.questions], "answers": {}}
    await db.flush()
    return {"questions": len(result.questions)}


async def tailor(db: AsyncSession, run_id: uuid.UUID) -> dict:
    run = await db.get(AssessmentRun, run_id)
    tenant = await company(db)
    intake = dict(run.intake_summary or {})
    qa = "\n".join(f"- {q['text']}\n  Answer: {intake.get('answers', {}).get(q['id']) or '(no answer)'}"
                   for q in intake.get("questions", []))

    domains = (await db.execute(select(RunDomain).where(RunDomain.run_id == run.id))).scalars().all()
    scope = await load_run_scope(db, run.assessment_version_id)
    name_of = {d.avd_id: d.name for d in scope.domains}
    keyed: dict[str, RunQuestion] = {}
    lines = []
    n = 0
    for rd in sorted(domains, key=lambda x: [d.avd_id for d in scope.domains].index(x.assessment_version_domain_id)):
        lines.append(f"\nDomain: {name_of[rd.assessment_version_domain_id]}")
        qs = (await db.execute(select(RunQuestion).where(RunQuestion.run_domain_id == rd.id, RunQuestion.kind == "base")
                               .order_by(RunQuestion.sort_order))).scalars().all()
        for q in qs:
            n += 1
            keyed[f"Q{n}"] = q
            lines.append(f"- Q{n}: {q.text}")

    prompt = (f"Company: {tenant.name}\nIndustry: {tenant.industry}\nEmployees: {tenant.employee_count}\n\n"
              f"Intake answers:\n{qa}\n\nQuestions:{''.join(chr(10) + line for line in lines)}")
    result = await ai.structured(output=Tailoring, system=TAILOR_SYSTEM, content=prompt, effort="medium", max_tokens=32000,
                                 usage=ai.UsageTag("tailoring", tenant_of(db), run.id))

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
