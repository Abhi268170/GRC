"""Assessment run helpers: creation, scope/keys, permissions, progress."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import ai_contracts as contracts
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import ControlSession, tenant_of
from app.models import (
    AppUser,
    AssessmentRun,
    AssessmentVersion,
    AssessmentVersionDomain,
    Conversation,
    Question,
    QuestionRequirement,
    RequirementEvaluation,
    RunDomain,
    RunQuestion,
    Tenant,
)
from app.services.question_gen import DomainScope, Req, load_scopes


def now() -> datetime:
    return datetime.now(UTC)


@dataclass
class RunScope:
    """Everything static about a run's assessment version: domains, requirements (with
    stable keys R1..Rn), and which requirements each base question covers."""

    domains: list[DomainScope]
    by_id: dict[uuid.UUID, Req] = field(default_factory=dict)
    by_key: dict[str, Req] = field(default_factory=dict)
    domain_of: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)  # req id -> avd id
    question_reqs: dict[uuid.UUID, list[uuid.UUID]] = field(default_factory=dict)  # question id -> req ids

    def reqs_for_domain(self, avd_id: uuid.UUID) -> list[Req]:
        return next((d.requirements for d in self.domains if d.avd_id == avd_id), [])


async def load_run_scope(db: AsyncSession, assessment_version_id: uuid.UUID) -> RunScope:
    domains = await load_scopes(db, assessment_version_id)
    scope = RunScope(domains=domains)
    for d in domains:
        for r in d.requirements:
            scope.by_id[r.id], scope.by_key[r.key], scope.domain_of[r.id] = r, r, d.avd_id
    rows = (await db.execute(
        select(QuestionRequirement.question_id, QuestionRequirement.requirement_version_id)
        .join(Question, Question.id == QuestionRequirement.question_id)
        .where(Question.assessment_version_id == assessment_version_id)
    )).all()
    for qid, rid in rows:
        scope.question_reqs.setdefault(qid, []).append(rid)
    return scope


async def question_requirements(db: AsyncSession, scope: RunScope, rq: RunQuestion) -> list[uuid.UUID]:
    """Requirements a run question covers (follow-ups inherit from their base question)."""
    base = rq
    while base.kind == "follow_up" and base.parent_run_question_id:
        base = await db.get(RunQuestion, base.parent_run_question_id)
    return scope.question_reqs.get(base.question_id, []) if base and base.question_id else []


async def create_run(db: AsyncSession, user: AppUser, version: AssessmentVersion) -> AssessmentRun:
    run = AssessmentRun(assessment_version_id=version.id, title=version.title,
                        status="intake", started_by=user.id, started_at=now())
    db.add(run)
    await db.flush()
    avds = (await db.execute(select(AssessmentVersionDomain).where(
        AssessmentVersionDomain.assessment_version_id == version.id).order_by(AssessmentVersionDomain.sort_order))).scalars().all()
    for avd in avds:
        rd = RunDomain(run_id=run.id, assessment_version_domain_id=avd.id)
        db.add(rd)
        await db.flush()
        questions = (await db.execute(select(Question).where(Question.assessment_version_domain_id == avd.id)
                                      .order_by(Question.sort_order))).scalars().all()
        for i, q in enumerate(questions):
            db.add(RunQuestion(run_id=run.id, run_domain_id=rd.id, question_id=q.id,
                               kind="base", text=q.text, sort_order=i * 10))
        db.add(Conversation(run_id=run.id, kind="domain", run_domain_id=rd.id, state={}))
    await db.flush()
    return run


# ---------- access ----------


async def get_run(db: AsyncSession, user: AppUser, run_id: uuid.UUID, lock: bool = False) -> AssessmentRun:
    """`lock=True` holds the run's row until the transaction ends, so two requests that change its
    status (submit twice, approve and request changes together) run one after the other."""
    run = await db.get(AssessmentRun, run_id, with_for_update=lock, populate_existing=lock)
    if run is None:  # another company's run isn't in this database at all
        raise HTTPException(404, "Assessment not found")
    return run


def can_review(user: AppUser, run: AssessmentRun) -> bool:
    return user.platform_role == "tenant_admin" or user.id == run.started_by


def can_work_on(user: AppUser, run: AssessmentRun, rd: RunDomain) -> bool:
    """Assignee, run starter and tenant admins can work on a domain; anyone if unassigned."""
    return rd.assignee_id is None or rd.assignee_id == user.id or can_review(user, run)


async def get_domain(db: AsyncSession, run: AssessmentRun, run_domain_id: uuid.UUID) -> RunDomain:
    rd = await db.get(RunDomain, run_domain_id)
    if rd is None or rd.run_id != run.id:
        raise HTTPException(404, "Domain not found")
    return rd


def require_editable(run: AssessmentRun, rd: RunDomain | None = None) -> None:
    if run.status not in ("in_progress", "changes_requested"):
        raise HTTPException(409, "This assessment isn't open for answers right now")
    if rd is not None and rd.status == "completed":
        raise HTTPException(409, "This domain is completed. Reopen it to make changes.")


async def company(db: AsyncSession) -> Tenant:
    """The company this database belongs to. Its profile is in the control database's registry."""
    async with ControlSession() as control:
        return await control.get(Tenant, tenant_of(db))


async def company_contract(db: AsyncSession, run: AssessmentRun | None = None) -> contracts.Company:
    """The company as the AI service gets it. With a run, includes the summary from its intake."""
    tenant = await company(db)
    summary = (run.intake_summary or {}).get("context_summary") if run is not None else None
    return contracts.Company(name=tenant.name, industry=tenant.industry, employees=tenant.employee_count,
                             context_summary=summary)


async def evaluations_by_req(db: AsyncSession, run_id: uuid.UUID) -> dict[uuid.UUID, RequirementEvaluation]:
    rows = (await db.execute(select(RequirementEvaluation).where(RequirementEvaluation.run_id == run_id))).scalars()
    return {e.requirement_version_id: e for e in rows}


async def current_question(db: AsyncSession, rd: RunDomain) -> RunQuestion | None:
    """The next pending question: base questions in order, each followed by its follow-ups."""
    rows = (await db.execute(select(RunQuestion).where(RunQuestion.run_domain_id == rd.id)
                             .order_by(RunQuestion.sort_order, RunQuestion.created_at))).scalars().all()
    return next((q for q in rows if q.status == "pending"), None)
