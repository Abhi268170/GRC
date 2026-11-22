"""Read helpers shared by the run endpoints: summaries, people, notifications, action and risk rows."""

import uuid
from fastapi import HTTPException
from sqlalchemy import func, select
from app.core.auth import TenantDB
from app.models import (
    ActionItem,
    ActionItemRequirement,
    AppUser,
    AssessmentRun,
    AssessmentVersion,
    Job,
    Notification,
    ReviewComment,
    Risk,
    RiskRequirement,
    RunDomain,
    RunQuestion,
    RunRollup,
)
from app.services import ai
from app.services import runs as svc
from app.api.runs.schemas import ActionOut, DomainSummary, Person, RiskOut, RunSummary


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

def _require_reviewer(me: AppUser, run: AssessmentRun, action: str) -> None:
    if not svc.can_review(me, run):
        raise HTTPException(403, f"Only the person who started this assessment or an admin can {action}")

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
