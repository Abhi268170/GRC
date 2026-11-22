"""AI question generation and requirement tagging for assessment versions.

Requirements are shown to the model with short keys (R1, R2, ...) so tags can be mapped
back to requirement_version ids exactly."""

import asyncio
import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
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

    @property
    def evidence_text(self) -> str:
        return "; ".join(self.evidence)


@dataclass
class ControlContext:
    """The descriptive fields of a control version, for the AI."""
    label: str
    area: str | None = None
    risk_exposure_level: str | None = None
    responsible_role: str | None = None
    classification: dict[str, list[str]] = field(default_factory=dict)  # category label -> value labels
    texts: dict[str, str] = field(default_factory=dict)  # field label -> text

    def render(self, detail: str = "full") -> str:
        """detail="full": everything; "brief": what the control is about (for question writing and intake)."""
        lines = [f"Control: {self.label}"]
        brief = ("Key requirement", "Why it matters", "Applies to", "Triggers")
        if self.area:
            lines.append(f"  Area: {self.area}")
        if self.responsible_role:
            lines.append(f"  Responsible role: {self.responsible_role}")
        for name, values in self.classification.items():
            if values and (detail == "full" or name == "Use case"):
                lines.append(f"  {name}: {', '.join(values)}")
        if self.risk_exposure_level and detail == "full":
            lines.append(f"  Company risk exposure: {self.risk_exposure_level}")
        for name, text in self.texts.items():
            if text and (detail == "full" or name in brief):
                lines.append(f"  {name}: {text}")
        return "\n".join(lines)


@dataclass
class DomainScope:
    avd_id: uuid.UUID
    name: str
    description: str | None
    requirements: list[Req]
    controls: dict[uuid.UUID, ControlContext] = field(default_factory=dict)  # control version id -> context


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


def requirement_line(r: Req, evidence_label: str = "Evidence") -> str:
    """'- R1: statement [mandatory]' then the guidance (how to meet it) and evidence (what proves it)."""
    bits = [f"- {r.key}: {r.statement}"]
    if r.mandatory is not None:
        bits.append("[mandatory]" if r.mandatory else "[optional]")
    line = " ".join(bits)
    if r.guidance:
        line += f"\n    How to meet it: {r.guidance}"
    if r.evidence:
        line += f"\n    {evidence_label}: {r.evidence_text}"
    return line


def render_requirements(scope: "DomainScope", detail: str = "full", evidence_label: str = "Evidence",
                        keys: set[str] | None = None) -> list[str]:
    """Requirements grouped under their control, with the control's context once per control."""
    lines: list[str] = []
    current = None
    for r in scope.requirements:
        if keys is not None and r.key not in keys:
            continue
        if r.control_version_id != current:
            current = r.control_version_id
            ctx = scope.controls.get(r.control_version_id) if r.control_version_id else None
            lines.append("")
            lines.append(ctx.render(detail) if ctx else f"Control: {r.control}")
        lines.append(requirement_line(r, evidence_label))
    return lines


class DomainQuestion(BaseModel):
    text: str = Field(description="The domain's single opening question, in plain conversational English.")
    help_text: str = Field(description="A one-line intro, then exactly one '- ' bullet per control, then one short line on useful evidence.")


class Tags(BaseModel):
    requirement_keys: list[str]


GEN_SYSTEM = """You write the single opening question for one domain of an AI-guided security and compliance assessment.

Each domain has exactly one question. It is an open, friendly invitation for the person to describe how their company handles this area in their own words. An AI guide then asks follow-up questions about anything the answer leaves out, so the question doesn't need to ask for every detail.

The question:
- Plain English and no jargon, one or two sentences. Ask what the company actually does, not whether it complies.
- It naturally invites information about every topic in the domain. You may name the main topics briefly.

The help text:
- One short intro line, then exactly one "- " bullet per control (the controls are listed below), each summarising that control's topic in a few words. Don't list individual requirements; the guide covers those in follow-ups.
- Then one short line on evidence that helps (documents, screenshots, exports).

Each control comes with its key requirement (what the company must have in place), why it matters, what it applies to (use cases) and the events that call for it (triggers). Use these to understand what each control is really about and to make the question concrete for the company, but don't copy them verbatim. Each requirement comes with guidance on how to meet it and the evidence that proves it. Requirements are marked [mandatory] or [optional] where the library says so; cover both.

The person answering is usually not a compliance expert (an IT manager, founder, or HR lead)."""

TAG_SYSTEM = """You map an assessment question to the requirements it gathers information for.
Return the keys of every requirement that a complete answer to the question would provide evidence for. Return an empty list if none apply. Only use the keys you are given."""


def _render(scope: DomainScope) -> str:
    lines = [f"Domain: {scope.name}"]
    if scope.description:
        lines.append(f"About this domain: {scope.description}")
    lines.append("\nControls and their requirements:")
    lines += render_requirements(scope, detail="brief", evidence_label="Expected evidence")
    return "\n".join(lines)


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


async def _generate_for(scope: DomainScope) -> DomainQuestion:
    return await ai.structured(output=DomainQuestion, system=GEN_SYSTEM, content=_render(scope), effort="medium", max_tokens=16000,
                               usage=ai.UsageTag("question_generation"))


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
    prompt = f"{_render(scope)}\n\nQuestion: {question.text}"
    if question.help_text:
        prompt += f"\nHelp text: {question.help_text}"
    result = await ai.structured(output=Tags, system=TAG_SYSTEM, content=prompt, model=ai.conversation_model(),
                                 effort="low", max_tokens=4000, usage=ai.UsageTag("question_tagging"))
    by_key = {r.key: r.id for r in scope.requirements}
    return list(dict.fromkeys(by_key[k] for k in result.requirement_keys if k in by_key))
