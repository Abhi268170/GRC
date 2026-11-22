"""Assessment builder (Super Admin) and the published catalog (tenants)."""

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.core.auth import ControlDB, CurrentUser, SuperAdmin
from app.core.queue import enqueue, enqueue_task
from app.models import (
    Assessment,
    AssessmentVersion,
    AssessmentVersionControl,
    AssessmentVersionDomain,
    Control,
    ControlVersion,
    DomainVersion,
    Job,
    Question,
    QuestionRequirement,
    Requirement,
    RequirementVersion,
)
from app.services import ai, question_gen, tenants
from app.services import versioning as v

router = APIRouter(prefix="/assessments", tags=["assessments"])


# ---------- schemas ----------


class VersionSummary(BaseModel):
    id: uuid.UUID
    version: int
    status: str
    title: str
    description: str | None
    generation_status: str
    published_at: datetime | None
    domain_count: int
    control_count: int
    question_count: int


class AssessmentOut(BaseModel):
    id: uuid.UUID
    code: str
    published: VersionSummary | None
    draft: VersionSummary | None
    run_count: int


class AssessmentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str | None = None
    control_ids: list[uuid.UUID] = Field(min_length=1)


class VersionEdit(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str | None = None


class ControlsEdit(BaseModel):
    control_ids: list[uuid.UUID] = Field(min_length=1)


class GenerateIn(BaseModel):
    mode: str = Field(default="all", pattern="^(all|uncovered)$")


class QuestionIn(BaseModel):
    assessment_version_domain_id: uuid.UUID
    text: str = Field(min_length=5)
    help_text: str | None = None


class QuestionEdit(BaseModel):
    text: str = Field(min_length=5)
    help_text: str | None = None


class TagsEdit(BaseModel):
    requirement_version_ids: list[uuid.UUID]


class OrderEdit(BaseModel):
    domain_ids: list[uuid.UUID]  # assessment_version_domain ids, in order
    questions: dict[uuid.UUID, list[uuid.UUID]]  # avd id -> question ids, in order


class ReqOut(BaseModel):
    id: uuid.UUID
    code: str
    statement: str
    mandatory: bool | None


class ControlOut(BaseModel):
    control_id: uuid.UUID
    control_version_id: uuid.UUID
    code: str
    title: str
    version: int
    requirements: list[ReqOut]


class QuestionOut(BaseModel):
    id: uuid.UUID
    text: str
    help_text: str | None
    sort_order: int
    origin: str
    requirement_ids: list[uuid.UUID]


class DomainOut(BaseModel):
    id: uuid.UUID  # assessment_version_domain id
    domain_id: uuid.UUID
    name: str
    sort_order: int
    controls: list[ControlOut]
    questions: list[QuestionOut]


class Coverage(BaseModel):
    total: int
    covered: int
    uncovered: list[uuid.UUID]


class JobOut(BaseModel):
    id: uuid.UUID
    type: str
    status: str
    error: str | None


class ControlUpdate(BaseModel):
    """A control in a draft whose version was superseded by a newer published one."""
    control_id: uuid.UUID
    code: str
    title: str
    current: str  # version code in the draft, e.g. IAM02.0001
    latest: str   # newest published version code


class VersionDetail(BaseModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    code: str
    version: int
    status: str
    title: str
    description: str | None
    generation_status: str
    published_at: datetime | None
    domains: list[DomainOut]
    coverage: Coverage
    latest_job: JobOut | None
    other_versions: list[VersionSummary]
    control_updates: list[ControlUpdate]  # drafts only: newer published control versions are available


# ---------- helpers ----------


async def _summary(db: ControlDB, av: AssessmentVersion) -> VersionSummary:
    domain_count = (await db.execute(select(func.count()).where(AssessmentVersionDomain.assessment_version_id == av.id))).scalar()
    control_count = (await db.execute(select(func.count()).where(AssessmentVersionControl.assessment_version_id == av.id))).scalar()
    question_count = (await db.execute(select(func.count()).where(Question.assessment_version_id == av.id))).scalar()
    return VersionSummary(id=av.id, version=av.version, status=av.status, title=av.title, description=av.description,
                          generation_status=av.generation_status, published_at=av.published_at,
                          domain_count=domain_count, control_count=control_count, question_count=question_count)


async def _draft(db: ControlDB, version_id: uuid.UUID) -> AssessmentVersion:
    av = await db.get(AssessmentVersion, version_id)
    if av is None:
        raise HTTPException(404, "Assessment version not found")
    if av.status != "draft":
        raise HTTPException(409, "Published versions can't be changed. Create a new draft instead.")
    return av


async def _not_generating(av: AssessmentVersion) -> None:
    if av.generation_status in ("pending", "processing"):
        raise HTTPException(409, "Questions are being generated. Try again when generation finishes.")


async def _snapshot_controls(db: ControlDB, av: AssessmentVersion, control_ids: list[uuid.UUID]) -> None:
    """(Re)build the domain/control snapshot for a draft from the current published control versions."""
    rows = (await db.execute(
        select(ControlVersion, Control.code)
        .join(Control, Control.id == ControlVersion.control_id)
        .where(ControlVersion.control_id.in_(control_ids), ControlVersion.status == "published")
    )).all()
    if len(rows) != len(set(control_ids)):
        raise HTTPException(422, "Every selected control must have a published version")

    existing = {avd.domain_version_id: avd for avd in (await db.execute(
        select(AssessmentVersionDomain).where(AssessmentVersionDomain.assessment_version_id == av.id)
    )).scalars()}
    await db.execute(delete(AssessmentVersionControl).where(AssessmentVersionControl.assessment_version_id == av.id))

    domain_versions = {dv.domain_id: dv for dv in (await db.execute(
        select(DomainVersion).where(DomainVersion.domain_id.in_({cv.domain_id for cv, _ in rows}),
                                    DomainVersion.status == "published")
    )).scalars()}
    keep: set[uuid.UUID] = set()
    by_domain: dict[uuid.UUID, list[tuple[ControlVersion, str]]] = {}
    for cv, code in rows:
        by_domain.setdefault(cv.domain_id, []).append((cv, code))
    ordered = sorted(by_domain, key=lambda d: domain_versions[d].name.lower())
    next_order = max([a.sort_order for a in existing.values()] or [-1]) + 1
    for domain_id in ordered:
        dv = domain_versions.get(domain_id)
        if dv is None:
            raise HTTPException(422, "A selected control's domain is not published")
        avd = existing.get(dv.id)
        if avd is None:
            avd = AssessmentVersionDomain(assessment_version_id=av.id, domain_version_id=dv.id, sort_order=next_order)
            next_order += 1
            db.add(avd)
            await db.flush()
        keep.add(avd.id)
        for i, (cv, _) in enumerate(sorted(by_domain[domain_id], key=lambda x: x[1])):
            db.add(AssessmentVersionControl(assessment_version_id=av.id, control_version_id=cv.id,
                                            assessment_version_domain_id=avd.id, sort_order=i))
    for avd in existing.values():
        if avd.id not in keep:
            await db.delete(avd)  # its questions cascade
    await db.flush()

    # Drop tags pointing at requirements no longer in scope.
    in_scope = select(RequirementVersion.id).join(
        AssessmentVersionControl, AssessmentVersionControl.control_version_id == RequirementVersion.control_version_id
    ).where(AssessmentVersionControl.assessment_version_id == av.id)
    await db.execute(delete(QuestionRequirement).where(
        QuestionRequirement.question_id.in_(select(Question.id).where(Question.assessment_version_id == av.id)),
        QuestionRequirement.requirement_version_id.not_in(in_scope),
    ))
    await db.flush()


async def _start_generation(db: ControlDB, av: AssessmentVersion, mode: str) -> None:
    av.generation_status = "pending"
    await enqueue(db, type="generate_questions", ref_type="assessment_version", ref_id=av.id, payload={"mode": mode})


def _slug(title: str) -> str:
    base = re.sub(r"[^A-Z0-9]+", "-", title.upper()).strip("-")[:40] or "ASSESSMENT"
    return f"{base}-{uuid.uuid4().hex[:4].upper()}"


# ---------- endpoints ----------


@router.get("", response_model=list[AssessmentOut])
async def list_assessments(db: ControlDB, _: SuperAdmin) -> list[AssessmentOut]:
    out = []
    run_counts = await tenants.run_counts()  # runs live in the company databases
    for a in (await db.execute(select(Assessment).order_by(Assessment.created_at.desc()))).scalars():
        published = await v.get_version(db, AssessmentVersion, "assessment_id", a.id, "published")
        draft = await v.get_version(db, AssessmentVersion, "assessment_id", a.id, "draft")
        out.append(AssessmentOut(id=a.id, code=a.code, run_count=run_counts.get(a.id, 0),
                                 published=await _summary(db, published) if published else None,
                                 draft=await _summary(db, draft) if draft else None))
    return out


@router.post("", response_model=VersionDetail, status_code=201)
async def create_assessment(body: AssessmentCreate, db: ControlDB, user: SuperAdmin) -> VersionDetail:
    a = Assessment(code=_slug(body.title), created_by=user.id)
    db.add(a)
    await db.flush()
    av = AssessmentVersion(assessment_id=a.id, version=1, status="draft", title=body.title, description=body.description)
    db.add(av)
    await db.flush()
    await _snapshot_controls(db, av, body.control_ids)
    await _start_generation(db, av, "all")
    return await get_version(av.id, db, user)


@router.get("/versions/{version_id}", response_model=VersionDetail)
async def get_version(version_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> VersionDetail:
    av = await db.get(AssessmentVersion, version_id)
    if av is None:
        raise HTTPException(404, "Assessment version not found")
    a = await db.get(Assessment, av.assessment_id)

    domains = (await db.execute(
        select(AssessmentVersionDomain, DomainVersion)
        .join(DomainVersion, DomainVersion.id == AssessmentVersionDomain.domain_version_id)
        .where(AssessmentVersionDomain.assessment_version_id == version_id)
        .order_by(AssessmentVersionDomain.sort_order)
    )).all()
    controls = (await db.execute(
        select(AssessmentVersionControl, ControlVersion, Control.code)
        .join(ControlVersion, ControlVersion.id == AssessmentVersionControl.control_version_id)
        .join(Control, Control.id == ControlVersion.control_id)
        .where(AssessmentVersionControl.assessment_version_id == version_id)
        .order_by(AssessmentVersionControl.sort_order)
    )).all()
    reqs = (await db.execute(
        select(RequirementVersion, Requirement.code)
        .join(Requirement, Requirement.id == RequirementVersion.requirement_id)
        .where(RequirementVersion.control_version_id.in_([cv.id for _, cv, _ in controls]))
        .order_by(RequirementVersion.sort_order)
    )).all() if controls else []
    questions = (await db.execute(
        select(Question).where(Question.assessment_version_id == version_id).order_by(Question.sort_order)
    )).scalars().all()
    tags = (await db.execute(
        select(QuestionRequirement).where(QuestionRequirement.question_id.in_([q.id for q in questions]))
    )).scalars().all() if questions else []

    reqs_by_cv: dict[uuid.UUID, list[ReqOut]] = {}
    for rv, code in reqs:
        reqs_by_cv.setdefault(rv.control_version_id, []).append(ReqOut(id=rv.id, code=code, statement=rv.statement, mandatory=rv.mandatory))
    tags_by_q: dict[uuid.UUID, list[uuid.UUID]] = {}
    for t in tags:
        tags_by_q.setdefault(t.question_id, []).append(t.requirement_version_id)

    all_req_ids = [r.id for lst in reqs_by_cv.values() for r in lst]
    covered = {rid for ids in tags_by_q.values() for rid in ids}
    job = (await db.execute(
        select(Job).where(Job.ref_id == version_id).order_by(Job.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    others = (await db.execute(
        select(AssessmentVersion).where(AssessmentVersion.assessment_id == a.id, AssessmentVersion.id != av.id)
        .order_by(AssessmentVersion.version.desc())
    )).scalars().all()

    updates: list[ControlUpdate] = []
    stale = [(cv, code) for _, cv, code in controls if cv.status != "published"]
    if av.status == "draft" and stale:
        latest = {cv.control_id: cv.version for cv in (await db.execute(
            select(ControlVersion).where(ControlVersion.control_id.in_([cv.control_id for cv, _ in stale]),
                                         ControlVersion.status == "published"))).scalars()}
        updates = [ControlUpdate(control_id=cv.control_id, code=code, title=cv.title, current=f"{code}.{cv.version:04d}",
                                 latest=f"{code}.{latest[cv.control_id]:04d}")
                   for cv, code in stale if cv.control_id in latest]

    return VersionDetail(
        id=av.id, assessment_id=a.id, code=a.code, version=av.version, status=av.status, title=av.title,
        description=av.description, generation_status=av.generation_status, published_at=av.published_at,
        domains=[
            DomainOut(
                id=avd.id, domain_id=dv.domain_id, name=dv.name, sort_order=avd.sort_order,
                controls=[ControlOut(control_id=cv.control_id, control_version_id=cv.id, code=code, title=cv.title,
                                     version=cv.version, requirements=reqs_by_cv.get(cv.id, []))
                          for avc, cv, code in controls if avc.assessment_version_domain_id == avd.id],
                questions=[QuestionOut(id=q.id, text=q.text, help_text=q.help_text, sort_order=q.sort_order,
                                       origin=q.origin, requirement_ids=tags_by_q.get(q.id, []))
                           for q in questions if q.assessment_version_domain_id == avd.id],
            )
            for avd, dv in domains
        ],
        coverage=Coverage(total=len(all_req_ids), covered=len([r for r in all_req_ids if r in covered]),
                          uncovered=[r for r in all_req_ids if r not in covered]),
        latest_job=JobOut(id=job.id, type=job.type, status=job.status, error=job.error) if job else None,
        other_versions=[await _summary(db, o) for o in others],
        control_updates=updates,
    )


@router.put("/versions/{version_id}", response_model=VersionDetail)
async def edit_version(version_id: uuid.UUID, body: VersionEdit, db: ControlDB, user: SuperAdmin) -> VersionDetail:
    av = await _draft(db, version_id)
    av.title, av.description = body.title, body.description
    await db.commit()
    return await get_version(version_id, db, user)


@router.put("/versions/{version_id}/controls", response_model=VersionDetail)
async def edit_controls(version_id: uuid.UUID, body: ControlsEdit, db: ControlDB, user: SuperAdmin) -> VersionDetail:
    av = await _draft(db, version_id)
    await _not_generating(av)
    await _snapshot_controls(db, av, body.control_ids)
    await db.commit()
    return await get_version(version_id, db, user)


@router.post("/versions/{version_id}/use-latest-controls", response_model=VersionDetail)
async def use_latest_controls(version_id: uuid.UUID, db: ControlDB, user: SuperAdmin) -> VersionDetail:
    """Move a draft to the newest published version of each of its controls.

    Question tags carry over for requirements whose statement and guidance didn't change; requirements that are new
    or reworded are left uncovered, and the AI rewrites the question of each domain that has uncovered requirements."""
    av = await _draft(db, version_id)
    await _not_generating(av)
    old_tags = (await db.execute(
        select(QuestionRequirement.question_id, QuestionRequirement.source, RequirementVersion.requirement_id,
               RequirementVersion.statement, RequirementVersion.guidance)
        .join(RequirementVersion, RequirementVersion.id == QuestionRequirement.requirement_version_id)
        .join(Question, Question.id == QuestionRequirement.question_id)
        .where(Question.assessment_version_id == av.id)
    )).all()
    control_ids = list((await db.execute(
        select(ControlVersion.control_id).join(AssessmentVersionControl,
                                               AssessmentVersionControl.control_version_id == ControlVersion.id)
        .where(AssessmentVersionControl.assessment_version_id == av.id)
    )).scalars())
    await _snapshot_controls(db, av, control_ids)

    in_scope = {req_id: (rv_id, st, gd) for rv_id, req_id, st, gd in (await db.execute(
        select(RequirementVersion.id, RequirementVersion.requirement_id, RequirementVersion.statement,
               RequirementVersion.guidance)
        .join(AssessmentVersionControl, AssessmentVersionControl.control_version_id == RequirementVersion.control_version_id)
        .where(AssessmentVersionControl.assessment_version_id == av.id)
    )).all()}
    kept = set((await db.execute(
        select(QuestionRequirement.question_id, QuestionRequirement.requirement_version_id)
        .join(Question, Question.id == QuestionRequirement.question_id).where(Question.assessment_version_id == av.id)
    )).all())
    for question_id, source, req_id, statement, guidance in old_tags:
        new = in_scope.get(req_id)
        if new and (new[1], new[2]) == (statement, guidance) and (question_id, new[0]) not in kept:
            db.add(QuestionRequirement(question_id=question_id, requirement_version_id=new[0], source=source))
            kept.add((question_id, new[0]))
    await db.flush()

    if {rv_id for rv_id, _, _ in in_scope.values()} - {rv for _, rv in kept}:
        await _start_generation(db, av, "uncovered")
    else:
        await db.commit()
    return await get_version(version_id, db, user)


@router.post("/versions/{version_id}/generate", response_model=VersionDetail)
async def generate(version_id: uuid.UUID, body: GenerateIn, db: ControlDB, user: SuperAdmin) -> VersionDetail:
    av = await _draft(db, version_id)
    await _not_generating(av)
    await _start_generation(db, av, body.mode)
    return await get_version(version_id, db, user)


@router.post("/versions/{version_id}/questions", response_model=VersionDetail, status_code=201)
async def add_question(version_id: uuid.UUID, body: QuestionIn, db: ControlDB, user: SuperAdmin) -> VersionDetail:
    av = await _draft(db, version_id)
    await _not_generating(av)
    avd = await db.get(AssessmentVersionDomain, body.assessment_version_domain_id)
    if avd is None or avd.assessment_version_id != av.id:
        raise HTTPException(422, "Domain is not part of this assessment")
    order = (await db.execute(select(func.coalesce(func.max(Question.sort_order) + 1, 0))
                              .where(Question.assessment_version_domain_id == avd.id))).scalar()
    q = Question(assessment_version_id=av.id, assessment_version_domain_id=avd.id, text=body.text.strip(),
                 help_text=(body.help_text or "").strip() or None, sort_order=order, origin="manual")
    db.add(q)
    await db.flush()
    await _retag(db, q)
    await db.commit()
    return await get_version(version_id, db, user)


async def _retag(db: ControlDB, q: Question) -> None:
    try:
        ids = await question_gen.tag_question(db, q)
    except ai.AIError as e:
        raise HTTPException(502, f"Couldn't tag the question automatically: {e}") from e
    await db.execute(delete(QuestionRequirement).where(QuestionRequirement.question_id == q.id))
    for rid in ids:
        db.add(QuestionRequirement(question_id=q.id, requirement_version_id=rid, source="ai"))
    await db.flush()


async def _question_in_draft(db: ControlDB, question_id: uuid.UUID) -> Question:
    q = await db.get(Question, question_id)
    if q is None:
        raise HTTPException(404, "Question not found")
    av = await _draft(db, q.assessment_version_id)
    await _not_generating(av)
    return q


@router.put("/questions/{question_id}", response_model=VersionDetail)
async def edit_question(question_id: uuid.UUID, body: QuestionEdit, db: ControlDB, user: SuperAdmin) -> VersionDetail:
    q = await _question_in_draft(db, question_id)
    changed = q.text.strip() != body.text.strip()
    q.text, q.help_text = body.text.strip(), (body.help_text or "").strip() or None
    if changed:
        if q.origin == "ai_generated":
            q.origin = "ai_generated_edited"
        await _retag(db, q)
    await db.commit()
    return await get_version(q.assessment_version_id, db, user)


@router.put("/questions/{question_id}/requirements", response_model=VersionDetail)
async def edit_question_tags(question_id: uuid.UUID, body: TagsEdit, db: ControlDB, user: SuperAdmin) -> VersionDetail:
    q = await _question_in_draft(db, question_id)
    scope = {r.id for s in await question_gen.load_scopes(db, q.assessment_version_id) for r in s.requirements}
    if not set(body.requirement_version_ids) <= scope:
        raise HTTPException(422, "Requirements must be part of this assessment")
    await db.execute(delete(QuestionRequirement).where(QuestionRequirement.question_id == q.id))
    for rid in dict.fromkeys(body.requirement_version_ids):
        db.add(QuestionRequirement(question_id=q.id, requirement_version_id=rid, source="manual"))
    await db.commit()
    return await get_version(q.assessment_version_id, db, user)


@router.delete("/questions/{question_id}", response_model=VersionDetail)
async def delete_question(question_id: uuid.UUID, db: ControlDB, user: SuperAdmin) -> VersionDetail:
    q = await _question_in_draft(db, question_id)
    vid = q.assessment_version_id
    await db.delete(q)
    await db.commit()
    return await get_version(vid, db, user)


@router.put("/versions/{version_id}/order", response_model=VersionDetail)
async def reorder(version_id: uuid.UUID, body: OrderEdit, db: ControlDB, user: SuperAdmin) -> VersionDetail:
    av = await _draft(db, version_id)
    avds = {a.id: a for a in (await db.execute(
        select(AssessmentVersionDomain).where(AssessmentVersionDomain.assessment_version_id == av.id))).scalars()}
    if set(body.domain_ids) != set(avds):
        raise HTTPException(422, "Domain order must list every domain exactly once")
    for i, did in enumerate(body.domain_ids):
        avds[did].sort_order = i
    questions = {q.id: q for q in (await db.execute(select(Question).where(Question.assessment_version_id == av.id))).scalars()}
    for did, qids in body.questions.items():
        for i, qid in enumerate(qids):
            q = questions.get(qid)
            if q is None or q.assessment_version_domain_id != did:
                raise HTTPException(422, "Questions can only be reordered within their domain")
            q.sort_order = i
    await db.commit()
    return await get_version(version_id, db, user)


@router.post("/versions/{version_id}/publish", response_model=VersionDetail)
async def publish(version_id: uuid.UUID, db: ControlDB, user: SuperAdmin) -> VersionDetail:
    av = await _draft(db, version_id)
    await _not_generating(av)
    detail = await get_version(version_id, db, user)
    if detail.coverage.total == 0:
        raise HTTPException(409, "Add at least one control before publishing")
    if detail.coverage.uncovered:
        raise HTTPException(409, f"{len(detail.coverage.uncovered)} requirement(s) have no question yet. "
                                 "Every requirement must be covered before publishing.")
    _, previous = await v.publish(db, AssessmentVersion, "assessment_id", av.assessment_id, user.id)
    await db.commit()
    if previous is not None:
        # Each company database has its own copy of the old version and its own runs on it.
        await enqueue_task("fanout_deprecation", str(previous.id), {
            "assessment_title": av.title, "old_version": previous.version, "new_version": av.version,
        })
    return await get_version(version_id, db, user)


@router.post("/{assessment_id}/draft", response_model=VersionDetail, status_code=201)
async def new_draft(assessment_id: uuid.UUID, db: ControlDB, user: SuperAdmin) -> VersionDetail:
    """New draft from the published version, picking up the latest published controls."""
    if await v.get_version(db, AssessmentVersion, "assessment_id", assessment_id, "draft"):
        raise HTTPException(409, "A draft already exists")
    current = await v.get_version(db, AssessmentVersion, "assessment_id", assessment_id, "published")
    if current is None:
        raise HTTPException(404, "Assessment not found")
    draft = AssessmentVersion(assessment_id=assessment_id, status="draft", title=current.title,
                              description=current.description, generation_status="done",
                              version=await v.next_version_number(db, AssessmentVersion, "assessment_id", assessment_id))
    db.add(draft)
    await db.flush()
    control_ids = list((await db.execute(
        select(ControlVersion.control_id).join(AssessmentVersionControl, AssessmentVersionControl.control_version_id == ControlVersion.id)
        .where(AssessmentVersionControl.assessment_version_id == current.id)
    )).scalars())
    await _snapshot_controls(db, draft, control_ids)

    # Keep the published version's domain order (the snapshot sorts new domains by name).
    old_order = dict((await db.execute(
        select(DomainVersion.domain_id, AssessmentVersionDomain.sort_order)
        .join(AssessmentVersionDomain, AssessmentVersionDomain.domain_version_id == DomainVersion.id)
        .where(AssessmentVersionDomain.assessment_version_id == current.id))).all())
    for avd, dv in (await db.execute(
            select(AssessmentVersionDomain, DomainVersion).join(DomainVersion, DomainVersion.id == AssessmentVersionDomain.domain_version_id)
            .where(AssessmentVersionDomain.assessment_version_id == draft.id))).all():
        avd.sort_order = old_order.get(dv.domain_id, len(old_order) + avd.sort_order)
    await db.flush()

    # Copy questions; remap tags by stable requirement identity to the new requirement versions.
    new_avd = {dv.domain_id: avd.id for avd, dv in (await db.execute(
        select(AssessmentVersionDomain, DomainVersion).join(DomainVersion, DomainVersion.id == AssessmentVersionDomain.domain_version_id)
        .where(AssessmentVersionDomain.assessment_version_id == draft.id))).all()}
    new_rv = dict((await db.execute(
        select(RequirementVersion.requirement_id, RequirementVersion.id)
        .join(AssessmentVersionControl, AssessmentVersionControl.control_version_id == RequirementVersion.control_version_id)
        .where(AssessmentVersionControl.assessment_version_id == draft.id))).all())
    old_q = (await db.execute(
        select(Question, DomainVersion.domain_id)
        .join(AssessmentVersionDomain, AssessmentVersionDomain.id == Question.assessment_version_domain_id)
        .join(DomainVersion, DomainVersion.id == AssessmentVersionDomain.domain_version_id)
        .where(Question.assessment_version_id == current.id))).all()
    for q, domain_id in old_q:
        if domain_id not in new_avd:
            continue
        copy = Question(assessment_version_id=draft.id, assessment_version_domain_id=new_avd[domain_id], text=q.text,
                        help_text=q.help_text, sort_order=q.sort_order, origin=q.origin)
        db.add(copy)
        await db.flush()
        old_tags = (await db.execute(
            select(RequirementVersion.requirement_id, QuestionRequirement.source)
            .join(QuestionRequirement, QuestionRequirement.requirement_version_id == RequirementVersion.id)
            .where(QuestionRequirement.question_id == q.id))).all()
        for req_id, source in old_tags:
            if req_id in new_rv:
                db.add(QuestionRequirement(question_id=copy.id, requirement_version_id=new_rv[req_id], source=source))
    await db.commit()
    return await get_version(draft.id, db, user)


@router.delete("/versions/{version_id}", status_code=204)
async def discard_draft(version_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> None:
    av = await _draft(db, version_id)
    await _not_generating(av)
    assessment_id = av.assessment_id
    await db.delete(av)
    await db.flush()
    if not (await db.execute(select(AssessmentVersion.id).where(AssessmentVersion.assessment_id == assessment_id))).first():
        await db.delete(await db.get(Assessment, assessment_id))
    await db.commit()


# ---------- catalog (tenants) ----------


class CatalogItem(BaseModel):
    assessment_id: uuid.UUID
    version_id: uuid.UUID
    version: int
    title: str
    description: str | None
    published_at: datetime | None
    domains: list[str]
    control_count: int
    question_count: int
    frameworks: list[str]


@router.get("/catalog/published", response_model=list[CatalogItem])
async def catalog(db: ControlDB, _: CurrentUser) -> list[CatalogItem]:
    from app.models import Framework, FrameworkClause, FrameworkVersion, RequirementClauseMap

    out = []
    for av in (await db.execute(select(AssessmentVersion).where(AssessmentVersion.status == "published")
                                .order_by(AssessmentVersion.published_at.desc()))).scalars():
        s = await _summary(db, av)
        names = (await db.execute(
            select(DomainVersion.name).join(AssessmentVersionDomain, AssessmentVersionDomain.domain_version_id == DomainVersion.id)
            .where(AssessmentVersionDomain.assessment_version_id == av.id).order_by(AssessmentVersionDomain.sort_order))).scalars().all()
        fws = (await db.execute(
            select(Framework.name).distinct()
            .join(FrameworkVersion, FrameworkVersion.framework_id == Framework.id)
            .join(FrameworkClause, FrameworkClause.framework_version_id == FrameworkVersion.id)
            .join(RequirementClauseMap, RequirementClauseMap.framework_clause_id == FrameworkClause.id)
            .join(RequirementVersion, RequirementVersion.id == RequirementClauseMap.requirement_version_id)
            .join(AssessmentVersionControl, AssessmentVersionControl.control_version_id == RequirementVersion.control_version_id)
            .where(AssessmentVersionControl.assessment_version_id == av.id))).scalars().all()
        out.append(CatalogItem(assessment_id=av.assessment_id, version_id=av.id, version=av.version, title=av.title,
                               description=av.description, published_at=av.published_at, domains=list(names),
                               control_count=s.control_count, question_count=s.question_count, frameworks=sorted(fws)))
    return out

