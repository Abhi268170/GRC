"""Question generation and requirement tagging for assessment versions, and the "scope" of an
assessment version: its domains, controls and requirements as the AI features use them.

Requirements get short keys (R1, R2, ...) so the AI's answers can be mapped back to
requirement_version ids exactly. The prompts live in the AI service; this module loads the
data, sends it, and saves the results."""

import asyncio
import uuid
from dataclasses import dataclass, field

import ai_contracts as contracts
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssessmentVersion,
    AssessmentVersionControl,
    AssessmentVersionDomain,
    Control,
    ControlVersion,
    ControlVersionClassification,
    DomainVersion,
    MasterDataItem,
    OrganisationalRole,
    Question,
    QuestionRequirement,
    RequirementVersion,
)
from app.services import ai


@dataclass
class Req:
    id: uuid.UUID
    key: str
    control: str  # "IAM02 Access reviews"
    statement: str
    guidance: str  # how to meet it
    evidence: list[str]  # what proves it
    mandatory: bool | None
    control_version_id: uuid.UUID | None = None
    action_templates: list[dict] = field(default_factory=list)  # [{"title", "description"}]
    risk_templates: list[dict] = field(default_factory=list)

    def contract(self) -> contracts.Requirement:
        return contracts.Requirement(key=self.key, statement=self.statement, guidance=self.guidance or "",
                                     evidence=list(self.evidence), mandatory=self.mandatory)


@dataclass
class ControlContext:
    """The descriptive fields of a control version, for the AI."""
    label: str
    area: str | None = None
    risk_exposure_level: str | None = None
    responsible_role: str | None = None
    classification: dict[str, list[str]] = field(default_factory=dict)  # category label -> value labels
    texts: dict[str, str] = field(default_factory=dict)  # field label -> text

    def contract(self) -> contracts.ControlContext:
        return contracts.ControlContext(
            label=self.label, area=self.area, risk_exposure_level=self.risk_exposure_level,
            responsible_role=self.responsible_role, classification=self.classification, texts=self.texts)


@dataclass
class DomainScope:
    avd_id: uuid.UUID
    name: str
    description: str | None
    requirements: list[Req]
    controls: dict[uuid.UUID, ControlContext] = field(default_factory=dict)  # control version id -> context

    def by_control(self, keep=None) -> list[tuple[ControlContext, list[Req]]]:
        """Requirements grouped under their control, in order. `keep` filters requirements;
        controls left without any are dropped."""
        groups: list[tuple[uuid.UUID | None, list[Req]]] = []
        for r in self.requirements:
            if keep is not None and not keep(r):
                continue
            if not groups or groups[-1][0] != r.control_version_id:
                groups.append((r.control_version_id, []))
            groups[-1][1].append(r)
        return [(self.controls.get(cv_id) or ControlContext(label=reqs[0].control), reqs) for cv_id, reqs in groups]

    def contract(self) -> contracts.DomainScope:
        return contracts.DomainScope(name=self.name, description=self.description, controls=[
            contracts.ControlScope(context=ctx.contract(), requirements=[r.contract() for r in reqs])
            for ctx, reqs in self.by_control()])


TEXT_LABELS = {
    "key_requirement": "Key requirement",
    "short_description": "Why it matters",
    "risk_exposure": "Impact if missing",
    "involved_parties": "Involved parties",
    "triggers": "Triggers",
    "supporting_documents": "Supporting documents",
    "special_considerations": "Special considerations",
    "subject_specific_support": "Specialist support",
}
CLASS_LABELS = {
    "control_type": "Control type",
    "protection_domain": "Protection domain",
    "security_capability": "Security capability",
    "protection_objective": "Protection objective",
    "use_case": "Use case",
}


async def load_scopes(db: AsyncSession, version_id: uuid.UUID) -> list[DomainScope]:
    rows = (await db.execute(
        select(AssessmentVersionDomain, DomainVersion, ControlVersion, Control.code, RequirementVersion)
        .join(DomainVersion, DomainVersion.id == AssessmentVersionDomain.domain_version_id)
        .join(AssessmentVersionControl, AssessmentVersionControl.assessment_version_domain_id == AssessmentVersionDomain.id)
        .join(ControlVersion, ControlVersion.id == AssessmentVersionControl.control_version_id)
        .join(Control, Control.id == ControlVersion.control_id)
        .join(RequirementVersion, RequirementVersion.control_version_id == ControlVersion.id)
        .where(AssessmentVersionDomain.assessment_version_id == version_id)
        .order_by(AssessmentVersionDomain.sort_order, AssessmentVersionControl.sort_order, RequirementVersion.sort_order)
    )).all()
    scopes: dict[uuid.UUID, DomainScope] = {}
    n = 0
    control_versions: dict[uuid.UUID, tuple[ControlVersion, str]] = {}
    for avd, dv, cv, code, rv in rows:
        scope = scopes.setdefault(avd.id, DomainScope(avd.id, dv.name, dv.description, []))
        n += 1
        scope.requirements.append(Req(
            id=rv.id, key=f"R{n}", control=f"{code} {cv.title}", statement=rv.statement, guidance=rv.guidance,
            evidence=list(rv.evidence or []), mandatory=rv.mandatory, control_version_id=cv.id,
            action_templates=list(rv.action_templates or []), risk_templates=list(rv.risk_templates or []),
        ))
        control_versions[cv.id] = (cv, code)
    contexts = await control_contexts(db, control_versions)
    for scope in scopes.values():
        scope.controls = {r.control_version_id: contexts[r.control_version_id] for r in scope.requirements}
    return list(scopes.values())


async def control_contexts(db: AsyncSession, cvs: dict[uuid.UUID, tuple[ControlVersion, str]]) -> dict[uuid.UUID, ControlContext]:
    if not cvs:
        return {}
    ids = list(cvs)
    single_ids = {x for cv, _ in cvs.values() for x in (cv.area_id, cv.company_risk_exposure_id) if x}
    items = {m.id: m for m in (await db.execute(select(MasterDataItem).where(MasterDataItem.id.in_(single_ids)))).scalars()} if single_ids else {}
    role_ids = {cv.responsible_role_id for cv, _ in cvs.values() if cv.responsible_role_id}
    roles = {r.id: r for r in (await db.execute(select(OrganisationalRole).where(OrganisationalRole.id.in_(role_ids)))).scalars()} if role_ids else {}
    classes = (await db.execute(
        select(ControlVersionClassification.control_version_id, MasterDataItem)
        .join(MasterDataItem, MasterDataItem.id == ControlVersionClassification.master_data_item_id)
        .where(ControlVersionClassification.control_version_id.in_(ids))
        .order_by(MasterDataItem.sort_order)
    )).all()
    out: dict[uuid.UUID, ControlContext] = {}
    for cv_id, (cv, code) in cvs.items():
        role = roles.get(cv.responsible_role_id)
        ctx = ControlContext(
            label=f"{code} {cv.title}",
            area=items[cv.area_id].label if cv.area_id in items else None,
            risk_exposure_level=items[cv.company_risk_exposure_id].label if cv.company_risk_exposure_id in items else None,
            responsible_role=f"{role.name} ({role.abbreviation})" if role else None,
            texts={label: getattr(cv, f) for f, label in TEXT_LABELS.items() if getattr(cv, f)},
        )
        for c_id, item in classes:
            if c_id == cv_id:
                ctx.classification.setdefault(CLASS_LABELS[item.category], []).append(item.label)
        out[cv_id] = ctx
    return out


async def covered_requirement_ids(db: AsyncSession, version_id: uuid.UUID) -> set[uuid.UUID]:
    return set((await db.execute(
        select(QuestionRequirement.requirement_version_id)
        .join(Question, Question.id == QuestionRequirement.question_id)
        .where(Question.assessment_version_id == version_id)
    )).scalars())


async def _generate_for(scope: DomainScope) -> contracts.DomainQuestion:
    return await ai.call("/questions/generate", contracts.GenerateQuestionIn(domain=scope.contract()),
                         contracts.DomainQuestion, ai.UsageTag("question_generation"))


async def generate(db: AsyncSession, version_id: uuid.UUID, mode: str = "all") -> dict:
    """One question per domain, covering every requirement in that domain.

    mode='all' rewrites every domain's question. mode='uncovered' rewrites only domains with
    uncovered requirements (for example after controls were added): that domain's first question
    is rewritten in place to cover everything, and other questions in the domain are kept."""
    version = await db.get(AssessmentVersion, version_id)
    if version is None or version.status != "draft":
        raise ai.AIError("Only draft assessment versions can be generated")
    scopes = await load_scopes(db, version_id)

    if mode == "all":
        await db.execute(delete(Question).where(Question.assessment_version_id == version_id))
        await db.flush()
        work = scopes
    else:
        covered = await covered_requirement_ids(db, version_id)
        work = [s for s in scopes if any(r.id not in covered for r in s.requirements)]

    results = await asyncio.gather(*(_generate_for(s) for s in work))

    for scope, q in zip(work, results, strict=True):
        existing = (await db.execute(select(Question).where(Question.assessment_version_domain_id == scope.avd_id)
                                     .order_by(Question.sort_order).limit(1))).scalar_one_or_none()
        row = existing or Question(assessment_version_id=version_id, assessment_version_domain_id=scope.avd_id, sort_order=0)
        row.text, row.help_text, row.origin = q.text.strip(), q.help_text.strip(), "ai_generated"
        if existing is None:
            db.add(row)
        await db.flush()
        await db.execute(delete(QuestionRequirement).where(QuestionRequirement.question_id == row.id))
        for r in scope.requirements:  # the domain question covers the whole domain by construction
            db.add(QuestionRequirement(question_id=row.id, requirement_version_id=r.id, source="ai"))
    await db.flush()
    return {"domains_written": len(work)}


async def tag_question(db: AsyncSession, question: Question) -> list[uuid.UUID]:
    """Ask the AI which requirements (within the question's domain) the question addresses."""
    scope = next((s for s in await load_scopes(db, question.assessment_version_id) if s.avd_id == question.assessment_version_domain_id), None)
    if scope is None:
        return []
    result = await ai.call(
        "/questions/tag",
        contracts.TagQuestionIn(domain=scope.contract(), question_text=question.text, help_text=question.help_text),
        contracts.Tags, ai.UsageTag("question_tagging"))
    by_key = {r.key: r.id for r in scope.requirements}
    return list(dict.fromkeys(by_key[k] for k in result.requirement_keys if k in by_key))
