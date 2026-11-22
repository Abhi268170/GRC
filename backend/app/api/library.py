"""Control library (Super Admin): domains, controls, requirements, clause mappings."""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text

from app.core.auth import ControlDB, SuperAdmin
from app.models import (
    Control,
    ControlVersion,
    ControlVersionClassification,
    Domain,
    DomainVersion,
    Framework,
    FrameworkClause,
    FrameworkVersion,
    MasterDataItem,
    OrganisationalRole,
    Requirement,
    RequirementClauseMap,
    RequirementVersion,
)
from app.services import versioning as v

router = APIRouter(prefix="/library", tags=["library"])


# ---------- schemas ----------


class DomainVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    status: str
    name: str
    description: str | None
    published_at: datetime | None


class DomainOut(BaseModel):
    id: uuid.UUID
    abbreviation: str
    published: DomainVersionOut | None
    draft: DomainVersionOut | None
    control_count: int


class DomainCreate(BaseModel):
    abbreviation: str = Field(min_length=2, max_length=6, pattern=r"^[A-Z]+$")
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None


class DomainEdit(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None


class ClauseRef(BaseModel):
    id: uuid.UUID
    framework_code: str
    ref: str
    title: str


class Option(BaseModel):
    """A master data value as shown on a control."""
    id: uuid.UUID
    code: str
    label: str
    is_active: bool


class RoleRef(BaseModel):
    id: uuid.UUID
    name: str
    abbreviation: str


class Template(BaseModel):
    """Action item or risk template: both parts are required when a template is given."""
    title: str = Field(min_length=2, max_length=300)
    description: str = Field(min_length=2, max_length=4000)


class RequirementOut(BaseModel):
    requirement_id: uuid.UUID
    code: str
    statement: str
    guidance: str
    mandatory: bool | None
    evidence: list[str]
    action_templates: list[Template]
    risk_templates: list[Template]
    sort_order: int
    clauses: list[ClauseRef]


TEXT_FIELDS = ("short_description", "key_requirement", "risk_exposure", "involved_parties", "triggers",
               "supporting_documents", "special_considerations", "subject_specific_support")
# API field -> master data category, for the several-per-control lists
MULTI_FIELDS = {
    "control_types": "control_type",
    "protection_domains": "protection_domain",
    "security_capabilities": "security_capability",
    "protection_objectives": "protection_objective",
    "use_cases": "use_case",
}


class ControlVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    version_code: str  # IAM02.0001
    status: str
    domain_id: uuid.UUID
    title: str
    area: Option | None
    company_risk_exposure: Option | None
    responsible_role: RoleRef | None
    control_types: list[Option]
    protection_domains: list[Option]
    security_capabilities: list[Option]
    protection_objectives: list[Option]
    use_cases: list[Option]
    short_description: str | None
    key_requirement: str | None
    risk_exposure: str | None
    involved_parties: str | None
    triggers: str | None
    supporting_documents: str | None
    special_considerations: str | None
    subject_specific_support: str | None
    published_at: datetime | None
    missing_for_publish: list[str]  # what still has to be filled in before this version can be published
    requirements: list[RequirementOut]


class ControlSummary(BaseModel):
    id: uuid.UUID
    code: str
    version_code: str
    domain_id: uuid.UUID
    title: str
    area: str | None
    version: int
    status: str  # status of the version shown (published if any, else draft)
    has_draft: bool
    imported: bool  # its draft came from an Excel import
    requirement_count: int
    frameworks: list[str]


class VersionListItem(BaseModel):
    id: uuid.UUID
    version: int
    version_code: str
    status: str
    published_at: datetime | None


class ControlDetail(BaseModel):
    id: uuid.UUID
    code: str
    domain_locked: bool  # the domain is part of the code, so it can't change once a version was published
    versions: list[VersionListItem]
    published: ControlVersionOut | None
    draft: ControlVersionOut | None


def _clean_lines(lines: list[str]) -> list[str]:
    return [x.strip() for x in lines if x and x.strip()]


class RequirementIn(BaseModel):
    requirement_id: uuid.UUID | None = None  # existing requirement identity (keeps history)
    statement: str = Field(min_length=5)
    guidance: str = Field(min_length=5, max_length=1000)  # short: how to meet the requirement
    mandatory: bool | None = None
    evidence: list[str] = []
    action_templates: list[Template] = []
    risk_templates: list[Template] = []
    clause_ids: list[uuid.UUID] = []


class ControlIn(BaseModel):
    domain_id: uuid.UUID
    title: str = Field(min_length=2, max_length=300)
    area_id: uuid.UUID | None = None
    company_risk_exposure_id: uuid.UUID | None = None
    responsible_role_id: uuid.UUID | None = None
    control_types: list[uuid.UUID] = []
    protection_domains: list[uuid.UUID] = []
    security_capabilities: list[uuid.UUID] = []
    protection_objectives: list[uuid.UUID] = []
    use_cases: list[uuid.UUID] = []
    short_description: str | None = None
    key_requirement: str | None = None
    risk_exposure: str | None = None
    involved_parties: str | None = None
    triggers: str | None = None
    supporting_documents: str | None = None
    special_considerations: str | None = None
    subject_specific_support: str | None = None
    requirements: list[RequirementIn] = Field(min_length=1, max_length=10)


MAX_REQUIREMENTS = 10


# ---------- domains ----------


def _dv(row: DomainVersion | None) -> DomainVersionOut | None:
    if row is None:
        return None
    return DomainVersionOut(
        id=row.id, version=row.version, status=row.status, name=row.name,
        description=row.description, published_at=row.published_at,
    )


@router.get("/domains", response_model=list[DomainOut])
async def list_domains(db: ControlDB, _: SuperAdmin) -> list[DomainOut]:
    domains = (await db.execute(select(Domain).order_by(Domain.abbreviation))).scalars().all()
    versions = (
        await db.execute(select(DomainVersion).where(DomainVersion.status.in_(("draft", "published"))))
    ).scalars().all()
    by_domain: dict[uuid.UUID, dict[str, DomainVersion]] = {}
    for dv in versions:
        by_domain.setdefault(dv.domain_id, {})[dv.status] = dv
    counts = dict(
        (
            await db.execute(
                select(ControlVersion.domain_id, func.count(func.distinct(ControlVersion.control_id)))
                .where(ControlVersion.status.in_(("draft", "published")))
                .group_by(ControlVersion.domain_id)
            )
        ).all()
    )
    out = [
        DomainOut(
            id=d.id, abbreviation=d.abbreviation,
            published=_dv(by_domain.get(d.id, {}).get("published")),
            draft=_dv(by_domain.get(d.id, {}).get("draft")),
            control_count=counts.get(d.id, 0),
        )
        for d in domains
    ]
    return sorted(out, key=lambda d: (d.published or d.draft).name.lower())


@router.post("/domains", response_model=DomainOut, status_code=201)
async def create_domain(body: DomainCreate, db: ControlDB, _: SuperAdmin) -> DomainOut:
    if (await db.execute(select(Domain.id).where(Domain.abbreviation == body.abbreviation))).first():
        raise HTTPException(409, f"Domain abbreviation {body.abbreviation} already exists")
    domain = Domain(abbreviation=body.abbreviation)
    db.add(domain)
    await db.flush()
    dv = DomainVersion(domain_id=domain.id, version=1, status="draft", name=body.name,
                       description=body.description)
    db.add(dv)
    await db.commit()
    return DomainOut(id=domain.id, abbreviation=domain.abbreviation, published=None, draft=_dv(dv), control_count=0)


@router.put("/domains/{domain_id}/draft", response_model=DomainVersionOut)
async def edit_domain_draft(domain_id: uuid.UUID, body: DomainEdit, db: ControlDB, _: SuperAdmin):
    draft = await v.require_draft(db, DomainVersion, "domain_id", domain_id)
    draft.name, draft.description = body.name, body.description
    await db.commit()
    return _dv(draft)


@router.post("/domains/{domain_id}/draft", response_model=DomainVersionOut, status_code=201)
async def new_domain_draft(domain_id: uuid.UUID, db: ControlDB, _: SuperAdmin):
    if await v.get_version(db, DomainVersion, "domain_id", domain_id, "draft"):
        raise HTTPException(409, "A draft already exists")
    current = await v.get_version(db, DomainVersion, "domain_id", domain_id, "published")
    if current is None:
        raise HTTPException(404, "Domain not found")
    draft = DomainVersion(
        domain_id=domain_id, status="draft", name=current.name, description=current.description,
        version=await v.next_version_number(db, DomainVersion, "domain_id", domain_id),
    )
    db.add(draft)
    await db.commit()
    return _dv(draft)


@router.post("/domains/{domain_id}/publish", response_model=DomainVersionOut)
async def publish_domain(domain_id: uuid.UUID, db: ControlDB, user: SuperAdmin):
    published, _prev = await v.publish(db, DomainVersion, "domain_id", domain_id, user.id)
    await db.commit()
    return _dv(published)


@router.delete("/domains/{domain_id}/draft", status_code=204)
async def discard_domain_draft(domain_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> None:
    draft = await v.require_draft(db, DomainVersion, "domain_id", domain_id)
    has_published = await v.get_version(db, DomainVersion, "domain_id", domain_id, "published")
    await db.delete(draft)
    if not has_published:  # never published: remove the domain entirely
        in_use = (await db.execute(select(ControlVersion.id).where(ControlVersion.domain_id == domain_id))).first()
        if in_use:
            raise HTTPException(409, "Move or delete this domain's controls first")
        await db.delete(await db.get(Domain, domain_id))
    await db.commit()




# ---------- controls ----------


def version_code(control_code: str, version: int) -> str:
    return f"{control_code}.{version:04d}"


async def _options(db: ControlDB, ids: list[uuid.UUID]) -> dict[uuid.UUID, MasterDataItem]:
    if not ids:
        return {}
    rows = (await db.execute(select(MasterDataItem).where(MasterDataItem.id.in_(ids)))).scalars().all()
    return {m.id: m for m in rows}


def _opt(m: MasterDataItem | None) -> Option | None:
    return Option(id=m.id, code=m.code, label=m.label, is_active=m.is_active) if m else None


def missing_for_publish(cv: ControlVersion, multi: dict[str, list[Option]], req_count: int) -> list[str]:
    missing = []
    if cv.area_id is None:
        missing.append("Area")
    if cv.responsible_role_id is None:
        missing.append("Organisational role")
    labels = {"control_types": "Control type", "protection_domains": "Protection domain",
              "security_capabilities": "Security capability", "protection_objectives": "Protection objective",
              "use_cases": "Use case"}
    missing += [label for field, label in labels.items() if not multi.get(field)]
    if not (cv.key_requirement or "").strip():
        missing.append("Key requirement")
    if not 1 <= req_count <= MAX_REQUIREMENTS:
        missing.append(f"1 to {MAX_REQUIREMENTS} requirements")
    return missing


async def _control_version_out(db: ControlDB, cv: ControlVersion | None, control_code: str) -> ControlVersionOut | None:
    if cv is None:
        return None
    rows = (
        await db.execute(
            select(RequirementVersion, Requirement.code)
            .join(Requirement, Requirement.id == RequirementVersion.requirement_id)
            .where(RequirementVersion.control_version_id == cv.id)
            .order_by(RequirementVersion.sort_order)
        )
    ).all()
    rv_ids = [rv.id for rv, _ in rows]
    clause_rows = (
        await db.execute(
            select(RequirementClauseMap.requirement_version_id, FrameworkClause, Framework.code)
            .join(FrameworkClause, FrameworkClause.id == RequirementClauseMap.framework_clause_id)
            .join(FrameworkVersion, FrameworkVersion.id == FrameworkClause.framework_version_id)
            .join(Framework, Framework.id == FrameworkVersion.framework_id)
            .where(RequirementClauseMap.requirement_version_id.in_(rv_ids))
            .order_by(Framework.code, FrameworkClause.sort_order)
        )
    ).all() if rv_ids else []
    clauses: dict[uuid.UUID, list[ClauseRef]] = {}
    for rv_id, clause, fw_code in clause_rows:
        clauses.setdefault(rv_id, []).append(
            ClauseRef(id=clause.id, framework_code=fw_code, ref=clause.ref, title=clause.title)
        )

    class_items = (await db.execute(
        select(MasterDataItem)
        .join(ControlVersionClassification, ControlVersionClassification.master_data_item_id == MasterDataItem.id)
        .where(ControlVersionClassification.control_version_id == cv.id)
        .order_by(MasterDataItem.sort_order)
    )).scalars().all()
    multi = {f: [_opt(m) for m in class_items if m.category == cat] for f, cat in MULTI_FIELDS.items()}
    singles = await _options(db, [x for x in (cv.area_id, cv.company_risk_exposure_id) if x])
    role = await db.get(OrganisationalRole, cv.responsible_role_id) if cv.responsible_role_id else None

    return ControlVersionOut(
        id=cv.id, version=cv.version, version_code=version_code(control_code, cv.version), status=cv.status,
        domain_id=cv.domain_id, title=cv.title,
        area=_opt(singles.get(cv.area_id)), company_risk_exposure=_opt(singles.get(cv.company_risk_exposure_id)),
        responsible_role=RoleRef(id=role.id, name=role.name, abbreviation=role.abbreviation) if role else None,
        **multi, **{f: getattr(cv, f) for f in TEXT_FIELDS},
        published_at=cv.published_at,
        missing_for_publish=missing_for_publish(cv, multi, len(rows)),
        requirements=[
            RequirementOut(requirement_id=rv.requirement_id, code=code, statement=rv.statement, guidance=rv.guidance,
                           mandatory=rv.mandatory,
                           evidence=rv.evidence or [], action_templates=rv.action_templates or [],
                           risk_templates=rv.risk_templates or [], sort_order=rv.sort_order,
                           clauses=clauses.get(rv.id, []))
            for rv, code in rows
        ],
    )


@router.get("/controls", response_model=list[ControlSummary])
async def list_controls(db: ControlDB, _: SuperAdmin, domain_id: uuid.UUID | None = None,
                        q: str | None = None) -> list[ControlSummary]:
    stmt = (
        select(ControlVersion, Control.code)
        .join(Control, Control.id == ControlVersion.control_id)
        .where(ControlVersion.status.in_(("draft", "published")))
    )
    if domain_id:
        stmt = stmt.where(ControlVersion.domain_id == domain_id)
    rows = (await db.execute(stmt)).all()

    shown: dict[uuid.UUID, tuple[ControlVersion, str]] = {}
    drafts: set[uuid.UUID] = set()
    imported: set[uuid.UUID] = set()
    for cv, code in rows:
        if cv.status == "draft":
            drafts.add(cv.control_id)
            if cv.import_id:
                imported.add(cv.control_id)
        if cv.control_id not in shown or cv.status == "published":
            shown[cv.control_id] = (cv, code)

    cv_ids = [cv.id for cv, _ in shown.values()]
    req_counts = dict((await db.execute(
        select(RequirementVersion.control_version_id, func.count())
        .where(RequirementVersion.control_version_id.in_(cv_ids))
        .group_by(RequirementVersion.control_version_id)
    )).all()) if cv_ids else {}
    fw_rows = (await db.execute(
        select(RequirementVersion.control_version_id, Framework.code).distinct()
        .join(RequirementClauseMap, RequirementClauseMap.requirement_version_id == RequirementVersion.id)
        .join(FrameworkClause, FrameworkClause.id == RequirementClauseMap.framework_clause_id)
        .join(FrameworkVersion, FrameworkVersion.id == FrameworkClause.framework_version_id)
        .join(Framework, Framework.id == FrameworkVersion.framework_id)
        .where(RequirementVersion.control_version_id.in_(cv_ids))
    )).all() if cv_ids else []
    fws: dict[uuid.UUID, list[str]] = {}
    for cv_id, fw in fw_rows:
        fws.setdefault(cv_id, []).append(fw)
    areas = await _options(db, [cv.area_id for cv, _ in shown.values() if cv.area_id])

    out = [
        ControlSummary(
            id=cv.control_id, code=code, version_code=version_code(code, cv.version), domain_id=cv.domain_id,
            title=cv.title, area=areas[cv.area_id].label if cv.area_id in areas else None, version=cv.version,
            status=cv.status, has_draft=cv.control_id in drafts, imported=cv.control_id in imported,
            requirement_count=req_counts.get(cv.id, 0), frameworks=sorted(fws.get(cv.id, [])),
        )
        for cv, code in shown.values()
    ]
    if q:
        needle = q.lower()
        out = [c for c in out if needle in c.title.lower() or needle in c.code.lower()]
    return sorted(out, key=lambda c: c.code)


@router.get("/controls/{control_id}", response_model=ControlDetail)
async def get_control(control_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> ControlDetail:
    control = await db.get(Control, control_id)
    if control is None:
        raise HTTPException(404, "Control not found")
    versions = (await db.execute(
        select(ControlVersion).where(ControlVersion.control_id == control_id).order_by(ControlVersion.version.desc())
    )).scalars().all()
    published = next((x for x in versions if x.status == "published"), None)
    draft = next((x for x in versions if x.status == "draft"), None)
    return ControlDetail(
        id=control.id, code=control.code,
        domain_locked=any(x.status != "draft" for x in versions),
        versions=[VersionListItem(id=x.id, version=x.version, version_code=version_code(control.code, x.version),
                                  status=x.status, published_at=x.published_at)
                  for x in versions],
        published=await _control_version_out(db, published, control.code),
        draft=await _control_version_out(db, draft, control.code),
    )


async def _next_control_code(db: ControlDB, domain_id: uuid.UUID) -> str:
    """Domain abbreviation + the next free 2-digit number in that domain (IAM01, IAM02, ...).

    A transaction-scoped advisory lock per domain makes concurrent creations in the same domain wait for
    each other, so two controls never get the same number. The lock is released on commit/rollback."""
    domain = await db.get(Domain, domain_id)
    if domain is None:
        raise HTTPException(422, "Domain not found")
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"control-code:{domain.abbreviation}"})
    prefix = domain.abbreviation
    codes = (await db.execute(select(Control.code).where(Control.code.like(f"{prefix}%")))).scalars().all()
    used = {int(c[len(prefix):]) for c in codes if c[len(prefix):].isdigit()}
    n = next(i for i in range(1, 1000) if i not in used)
    if n > 99:
        raise HTTPException(409, f"Domain {prefix} already has 99 controls")
    return f"{prefix}{n:02d}"


async def _apply_fields(db: ControlDB, cv: ControlVersion, body: ControlIn) -> None:
    """Copy the control's fields onto a draft version, checking every master data value is from the right list."""
    singles = {"area_id": "area", "company_risk_exposure_id": "company_risk_exposure"}
    ids = [getattr(body, f) for f in singles if getattr(body, f)] + [i for f in MULTI_FIELDS for i in getattr(body, f)]
    items = await _options(db, ids)
    for field, category in singles.items():
        value = getattr(body, field)
        if value and (value not in items or items[value].category != category):
            raise HTTPException(422, f"Invalid {category.replace('_', ' ')} value")
    for field, category in MULTI_FIELDS.items():
        if any(i not in items or items[i].category != category for i in getattr(body, field)):
            raise HTTPException(422, f"Invalid {category.replace('_', ' ')} value")
    if body.responsible_role_id and await db.get(OrganisationalRole, body.responsible_role_id) is None:
        raise HTTPException(422, "Invalid organisational role")

    cv.title, cv.domain_id = body.title.strip(), body.domain_id
    cv.area_id, cv.company_risk_exposure_id = body.area_id, body.company_risk_exposure_id
    cv.responsible_role_id = body.responsible_role_id
    for f in TEXT_FIELDS:
        setattr(cv, f, (getattr(body, f) or "").strip() or None)
    await db.execute(delete(ControlVersionClassification).where(ControlVersionClassification.control_version_id == cv.id))
    for i in dict.fromkeys(i for f in MULTI_FIELDS for i in getattr(body, f)):
        db.add(ControlVersionClassification(control_version_id=cv.id, master_data_item_id=i))
    await db.flush()


def _req_code(control_code: str, n: int) -> str:
    return f"{control_code}-R{n:02d}"


async def _write_requirements(db: ControlDB, control: Control, cv: ControlVersion, reqs: list[RequirementIn]) -> None:
    existing = (await db.execute(select(Requirement.code).where(Requirement.control_id == control.id))).scalars().all()
    next_n = max([int(c.rsplit("-R", 1)[1]) for c in existing if c.rsplit("-R", 1)[-1].isdigit()] or [0]) + 1
    seen: set[uuid.UUID] = set()
    for order, r in enumerate(reqs, start=1):
        if r.requirement_id:
            req = await db.get(Requirement, r.requirement_id)
            if req is None or req.control_id != control.id or r.requirement_id in seen:
                raise HTTPException(422, "Invalid requirement reference")
        else:
            req = Requirement(control_id=control.id, code=_req_code(control.code, next_n))
            next_n += 1
            db.add(req)
            await db.flush()
        seen.add(req.id)
        rv = RequirementVersion(
            requirement_id=req.id, control_version_id=cv.id, statement=r.statement.strip(), guidance=r.guidance.strip(),
            mandatory=r.mandatory,
            evidence=_clean_lines(r.evidence),
            action_templates=[{"title": t.title.strip(), "description": t.description.strip()} for t in r.action_templates],
            risk_templates=[{"title": t.title.strip(), "description": t.description.strip()} for t in r.risk_templates],
            sort_order=order,
        )
        db.add(rv)
        await db.flush()
        for clause_id in dict.fromkeys(r.clause_ids):
            db.add(RequirementClauseMap(requirement_version_id=rv.id, framework_clause_id=clause_id, source="manual"))
    await db.flush()


async def _recode(db: ControlDB, control: Control, domain_id: uuid.UUID) -> None:
    """A never-published control moved to another domain gets a code in that domain."""
    control.code = await _next_control_code(db, domain_id)
    reqs = (await db.execute(select(Requirement).where(Requirement.control_id == control.id)
                             .order_by(Requirement.code))).scalars().all()
    for req in reqs:
        req.code = f"tmp-{req.id}"  # avoid clashing with codes being reassigned
    await db.flush()
    for n, req in enumerate(reqs, start=1):
        req.code = _req_code(control.code, n)
    await db.flush()


@router.post("/controls", response_model=ControlDetail, status_code=201)
async def create_control(body: ControlIn, db: ControlDB, user: SuperAdmin) -> ControlDetail:
    control = Control(code=await _next_control_code(db, body.domain_id))
    db.add(control)
    await db.flush()
    cv = ControlVersion(control_id=control.id, version=1, status="draft", domain_id=body.domain_id, title=body.title)
    db.add(cv)
    await db.flush()
    await _apply_fields(db, cv, body)
    await _write_requirements(db, control, cv, body.requirements)
    await db.commit()
    return await get_control(control.id, db, user)


@router.put("/controls/{control_id}/draft", response_model=ControlDetail)
async def edit_control_draft(control_id: uuid.UUID, body: ControlIn, db: ControlDB, user: SuperAdmin) -> ControlDetail:
    control = await db.get(Control, control_id)
    if control is None:
        raise HTTPException(404, "Control not found")
    draft = await v.require_draft(db, ControlVersion, "control_id", control_id)
    if body.domain_id != draft.domain_id:
        if (await db.execute(select(ControlVersion.id).where(ControlVersion.control_id == control_id,
                                                             ControlVersion.status != "draft"))).first():
            raise HTTPException(409, "The domain is part of the control code, so it can't change after publishing")
        await _recode(db, control, body.domain_id)
    await _apply_fields(db, draft, body)
    for rv in (await db.execute(select(RequirementVersion).where(RequirementVersion.control_version_id == draft.id))).scalars():
        await db.delete(rv)  # draft requirement rows are replaced wholesale (mappings cascade)
    await db.flush()
    await _write_requirements(db, control, draft, body.requirements)
    await db.commit()
    return await get_control(control_id, db, user)


@router.post("/controls/{control_id}/draft", response_model=ControlDetail, status_code=201)
async def new_control_draft(control_id: uuid.UUID, db: ControlDB, user: SuperAdmin) -> ControlDetail:
    if await v.get_version(db, ControlVersion, "control_id", control_id, "draft"):
        raise HTTPException(409, "A draft already exists")
    current = await v.get_version(db, ControlVersion, "control_id", control_id, "published")
    if current is None:
        raise HTTPException(404, "Control not found")
    draft = ControlVersion(
        control_id=control_id, status="draft", domain_id=current.domain_id, title=current.title,
        area_id=current.area_id, company_risk_exposure_id=current.company_risk_exposure_id,
        responsible_role_id=current.responsible_role_id, **{f: getattr(current, f) for f in TEXT_FIELDS},
        version=await v.next_version_number(db, ControlVersion, "control_id", control_id),
    )
    db.add(draft)
    await db.flush()
    for (item_id,) in (await db.execute(select(ControlVersionClassification.master_data_item_id)
                                        .where(ControlVersionClassification.control_version_id == current.id))).all():
        db.add(ControlVersionClassification(control_version_id=draft.id, master_data_item_id=item_id))
    for rv in (await db.execute(select(RequirementVersion).where(RequirementVersion.control_version_id == current.id))).scalars().all():
        copy = RequirementVersion(requirement_id=rv.requirement_id, control_version_id=draft.id, statement=rv.statement,
                                  guidance=rv.guidance, mandatory=rv.mandatory, evidence=rv.evidence, action_templates=rv.action_templates,
                                  risk_templates=rv.risk_templates, sort_order=rv.sort_order)
        db.add(copy)
        await db.flush()
        for m in (await db.execute(select(RequirementClauseMap).where(RequirementClauseMap.requirement_version_id == rv.id))).scalars():
            db.add(RequirementClauseMap(requirement_version_id=copy.id, framework_clause_id=m.framework_clause_id, source=m.source))
    await db.commit()
    return await get_control(control_id, db, user)


@router.post("/controls/{control_id}/publish", response_model=ControlDetail)
async def publish_control(control_id: uuid.UUID, db: ControlDB, user: SuperAdmin) -> ControlDetail:
    draft = await v.require_draft(db, ControlVersion, "control_id", control_id)
    if not await v.get_version(db, DomainVersion, "domain_id", draft.domain_id, "published"):
        raise HTTPException(409, "Publish the control's domain first")
    control = await db.get(Control, control_id)
    out = await _control_version_out(db, draft, control.code)
    if out.missing_for_publish:
        raise HTTPException(409, "Fill in before publishing: " + ", ".join(out.missing_for_publish))
    await v.publish(db, ControlVersion, "control_id", control_id, user.id)
    await db.commit()
    return await get_control(control_id, db, user)


@router.delete("/controls/{control_id}/draft", status_code=204)
async def discard_control_draft(control_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> None:
    draft = await v.require_draft(db, ControlVersion, "control_id", control_id)
    has_published = await v.get_version(db, ControlVersion, "control_id", control_id, "published")
    await db.delete(draft)
    if not has_published:
        await db.flush()
        for req in (await db.execute(select(Requirement).where(Requirement.control_id == control_id))).scalars():
            await db.delete(req)
        await db.delete(await db.get(Control, control_id))
    await db.commit()
