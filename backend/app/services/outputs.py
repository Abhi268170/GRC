"""Completion outputs: formula roll-ups (PROJECT_IDEA §7.2), framework coverage, and AI-written
explanations, action items, risks and report. Scores are calculated, never decided by the AI."""

import uuid
from collections import defaultdict
from statistics import mean

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import tenant_of
from app.models import (
    ActionItem,
    ActionItemRequirement,
    AssessmentRun,
    AssessmentVersion,
    AssessmentVersionControl,
    Control,
    ControlVersion,
    Framework,
    FrameworkClause,
    FrameworkVersion,
    Report,
    RequirementClauseMap,
    RequirementVersion,
    Risk,
    RiskRequirement,
    RunRollup,
)
from app.services import ai
from app.services.question_gen import Req
from app.services.runs import company, evaluations_by_req, load_run_scope, now

TARGET = 3  # framework coverage target maturity


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 1) if values else None


async def compute_rollups(db: AsyncSession, run: AssessmentRun) -> dict:
    scope = await load_run_scope(db, run.assessment_version_id)
    evals = await evaluations_by_req(db, run.id)

    cv_rows = (await db.execute(
        select(ControlVersion.id, Control.code, ControlVersion.title, RequirementVersion.id, AssessmentVersionControl.assessment_version_domain_id)
        .join(Control, Control.id == ControlVersion.control_id)
        .join(AssessmentVersionControl, AssessmentVersionControl.control_version_id == ControlVersion.id)
        .join(RequirementVersion, RequirementVersion.control_version_id == ControlVersion.id)
        .where(AssessmentVersionControl.assessment_version_id == run.assessment_version_id)
    )).all()
    control_reqs: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    control_meta: dict[uuid.UUID, tuple[str, str, uuid.UUID]] = {}
    for cv_id, code, title, rv_id, avd_id in cv_rows:
        control_reqs[cv_id].append(rv_id)
        control_meta[cv_id] = (code, title, avd_id)

    def applicable(rids: list[uuid.UUID]) -> list[int]:
        return [evals[r].rating for r in rids if r in evals and not evals[r].is_na and evals[r].rating is not None]

    controls = {}
    for cv_id, rids in control_reqs.items():
        ratings = applicable(rids)
        controls[cv_id] = {"code": control_meta[cv_id][0], "title": control_meta[cv_id][1], "domain": control_meta[cv_id][2],
                           "score": _avg(ratings), "weakest": 0 in ratings}
    domains = {}
    for d in scope.domains:
        cs = [c for c in controls.values() if c["domain"] == d.avd_id]
        domains[d.avd_id] = {"name": d.name, "score": _avg([c["score"] for c in cs if c["score"] is not None]),
                             "weakest": any(c["weakest"] for c in cs)}
    overall = _avg([x["score"] for x in domains.values() if x["score"] is not None])

    # Framework coverage: of the assessable clauses mapped to applicable requirements in this run,
    # the share whose mapped applicable requirements all reach the target maturity.
    rv_ids = list(scope.by_id)
    maps = (await db.execute(
        select(RequirementClauseMap.requirement_version_id, FrameworkClause.id, FrameworkClause.is_assessable,
               FrameworkVersion.id, Framework.name, FrameworkVersion.version_label)
        .join(FrameworkClause, FrameworkClause.id == RequirementClauseMap.framework_clause_id)
        .join(FrameworkVersion, FrameworkVersion.id == FrameworkClause.framework_version_id)
        .join(Framework, Framework.id == FrameworkVersion.framework_id)
        .where(RequirementClauseMap.requirement_version_id.in_(rv_ids))
    )).all()
    clause_reqs: dict[tuple[uuid.UUID, uuid.UUID], list[uuid.UUID]] = defaultdict(list)
    fw_names: dict[uuid.UUID, str] = {}
    for rv_id, clause_id, assessable, fv_id, fw_name, label in maps:
        if assessable:
            clause_reqs[(fv_id, clause_id)].append(rv_id)
            fw_names[fv_id] = f"{fw_name} {label}"
    frameworks = {}
    for fv_id, name in fw_names.items():
        considered = met = 0
        for (fv, _clause), rids in clause_reqs.items():
            if fv != fv_id:
                continue
            ratings = applicable(rids)
            if not ratings:
                continue
            considered += 1
            met += all(r >= TARGET for r in ratings)
        frameworks[fv_id] = {"name": name, "covered": met, "considered": considered,
                             "pct": round(100 * met / considered, 1) if considered else None}

    await db.execute(delete(RunRollup).where(RunRollup.run_id == run.id))
    for cv_id, c in controls.items():
        db.add(RunRollup(run_id=run.id, level="control", ref_id=cv_id, score=c["score"], has_weakest_link=c["weakest"]))
    for avd_id, d in domains.items():
        db.add(RunRollup(run_id=run.id, level="domain", ref_id=avd_id, score=d["score"], has_weakest_link=d["weakest"]))
    db.add(RunRollup(run_id=run.id, level="assessment", ref_id=run.assessment_version_id, score=overall,
                     has_weakest_link=any(d["weakest"] for d in domains.values())))
    for fv_id, f in frameworks.items():
        db.add(RunRollup(run_id=run.id, level="framework", ref_id=fv_id, score=f["pct"]))
    await db.flush()
    return {"overall": overall, "domains": domains, "controls": controls, "frameworks": frameworks, "scope": scope, "evals": evals}


class DomainNarrative(BaseModel):
    domain: str
    summary: str = Field(description="Two to three sentences on this domain's state.")
    strengths: list[str]
    gaps: list[str]
    score_explanation: str = Field(description="One or two sentences explaining the calculated score (which requirements pulled it up or down).")


class SuggestedAction(BaseModel):
    title: str = Field(description="Imperative, specific, e.g. 'Enforce MFA for all admin accounts'.")
    description: str = Field(description="What to do and what 'done' looks like.")
    priority: str = Field(description="One of: low, medium, high, critical.")
    requirement_keys: list[str]


class SuggestedRisk(BaseModel):
    title: str
    description: str = Field(description="The risk scenario: what could happen, why, and the impact.")
    category: str = Field(description="One of: security, compliance, operational, third_party, data_privacy.")
    likelihood: int = Field(description="1 (rare) to 5 (almost certain).")
    impact: int = Field(description="1 (negligible) to 5 (severe).")
    requirement_keys: list[str]


class AdaptedAction(BaseModel):
    template_id: str = Field(description="The action template id, e.g. A3.")
    title: str = Field(description="The template's title adapted to the company: imperative and specific.")
    description: str = Field(description="The template's description adapted to the company: what to do and what 'done' looks like.")
    priority: str = Field(description="One of: low, medium, high, critical.")


class AdaptedRisk(BaseModel):
    template_id: str = Field(description="The risk template id, e.g. K2.")
    title: str
    description: str = Field(description="The template's risk adapted to the company: what could happen, why, and the impact.")
    category: str = Field(description="One of: security, compliance, operational, third_party, data_privacy.")
    likelihood: int = Field(description="1 (rare) to 5 (almost certain).")
    impact: int = Field(description="1 (negligible) to 5 (severe).")


class Narrative(BaseModel):
    executive_summary: str = Field(description="One short paragraph for leadership: overall posture, the most important gaps, and what to do first.")
    overall_explanation: str = Field(description="One or two sentences explaining the overall calculated score.")
    domains: list[DomainNarrative]
    adapted_actions: list[AdaptedAction] = Field(description="Exactly one per action template listed.")
    adapted_risks: list[AdaptedRisk] = Field(description="Exactly one per risk template listed.")
    action_items: list[SuggestedAction] = Field(description="New action items, only for gaps listed as having no action template.")
    risks: list[SuggestedRisk] = Field(description="New risks, only for gaps listed as having no risk template.")


SYSTEM = """You write the results of a completed security and compliance assessment.

Scores are already calculated by formula; explain them, don't change them. Ground everything in the ratings and rationales provided.

A gap is a requirement rated below 3. Action items and risks start from the control library's templates:
- Adapted actions and risks: return exactly one adapted item for every template listed, using its id. Keep the template's intent, and adapt the wording to this company: its size, industry, systems, and what the ratings and rationales say is already in place or missing. Don't drop, merge or add templates.
- Set each action's priority from how weak the requirement is (0 or 1 means high or critical) and the risk it leaves. Score each risk's likelihood and impact honestly.
- New action items and risks: write them only for the gaps listed as having no template, each tied to the requirements behind it. Group closely related gaps into one item. Return empty lists when every gap has templates.
- Each control comes with context from the control library. Use "Impact if missing" and the company risk exposure to describe and score risks, the protection objectives to say what is at stake, and the responsible role to say who should own an action.
- Write plainly for a non-specialist audience. No hype."""

PRIORITIES = {"low", "medium", "high", "critical"}
CATEGORIES = {"security", "compliance", "operational", "third_party", "data_privacy"}


async def generate(db: AsyncSession, run_id: uuid.UUID) -> dict:
    run = await db.get(AssessmentRun, run_id)
    tenant = await company(db)
    version = await db.get(AssessmentVersion, run.assessment_version_id)
    r = await compute_rollups(db, run)
    scope, evals = r["scope"], r["evals"]

    lines = [f"Company: {tenant.name} ({tenant.industry}, {tenant.employee_count} employees)",
             f"Assessment: {version.title}", f"Overall score: {r['overall']} / 4", ""]
    for d in scope.domains:
        dom = r["domains"][d.avd_id]
        lines.append(f"## {d.name} - score {dom['score']}{' (has a requirement rated 0)' if dom['weakest'] else ''}")
        current = None
        for req in d.requirements:
            if req.control_version_id != current:
                current = req.control_version_id
                ctx = d.controls.get(current)
                lines.append(ctx.render("full") if ctx else f"Control: {req.control}")
            e = evals.get(req.id)
            rating = "not rated" if e is None else ("N/A" if e.is_na else str(e.rating))
            flag = " [mandatory]" if req.mandatory else ""
            lines.append(f"- {req.key}{flag} {req.statement} -> {rating}. {e.rationale if e else ''}")
            if req.guidance:
                lines.append(f"    How to meet it: {req.guidance}")
        lines.append("")
    lines.append("Framework coverage (clauses at maturity 3+): " + "; ".join(
        f"{f['name']}: {f['pct']}% ({f['covered']}/{f['considered']})" for f in r["frameworks"].values()))

    # Gaps and their templates. Template ids are short (A1, K1) so the AI's answers map back exactly.
    gaps = [req for d in scope.domains for req in d.requirements
            if (e := evals.get(req.id)) is not None and not e.is_na and e.rating is not None and e.rating < TARGET]
    action_slots: dict[str, tuple[Req, dict]] = {}
    risk_slots: dict[str, tuple[Req, dict]] = {}
    for req in gaps:
        for t in req.action_templates:
            action_slots[f"A{len(action_slots) + 1}"] = (req, t)
        for t in req.risk_templates:
            risk_slots[f"K{len(risk_slots) + 1}"] = (req, t)
    free_action_keys = [req.key for req in gaps if not req.action_templates]
    free_risk_keys = [req.key for req in gaps if not req.risk_templates]
    rating_of = {req.key: evals[req.id].rating for req in gaps}
    lines += ["", "Action templates to adapt (one adapted action each):"]
    lines += [f"- {tid} for {req.key} (rated {rating_of[req.key]}): {t['title']}. {t['description']}" for tid, (req, t) in action_slots.items()] or ["(none)"]
    lines += ["", "Risk templates to adapt (one adapted risk each):"]
    lines += [f"- {tid} for {req.key} (rated {rating_of[req.key]}): {t['title']}. {t['description']}" for tid, (req, t) in risk_slots.items()] or ["(none)"]
    lines += ["", f"Gaps with no action template (write new action items only for these): {', '.join(free_action_keys) or '(none)'}",
              f"Gaps with no risk template (write new risks only for these): {', '.join(free_risk_keys) or '(none)'}"]

    n = await ai.structured(output=Narrative, system=SYSTEM, content="\n".join(lines), effort="medium", max_tokens=32000,
                            usage=ai.UsageTag("results", tenant_of(db), run.id))

    # Replace AI suggestions (and dismissals of them) from any previous generation of this run's outputs.
    # Results are only regenerated before approval, so nothing has been accepted into the registers yet.
    await db.execute(delete(ActionItem).where(ActionItem.run_id == run.id, ActionItem.status.in_(("suggested", "dismissed")),
                                              ActionItem.origin.in_(("ai", "template"))))
    await db.execute(delete(Risk).where(Risk.run_id == run.id, Risk.status.in_(("suggested", "dismissed")),
                                        Risk.origin.in_(("ai", "template"))))

    async def add_action(title: str, description: str, priority: str, origin: str, req_ids: list) -> None:
        item = ActionItem(run_id=run.id, title=title, description=description,
                          priority=priority if priority in PRIORITIES else "medium", status="suggested", origin=origin)
        db.add(item)
        await db.flush()
        for rid in dict.fromkeys(req_ids):
            db.add(ActionItemRequirement(action_item_id=item.id, requirement_version_id=rid))

    async def add_risk(title: str, description: str, category: str, likelihood: int, impact: int, origin: str, req_ids: list) -> None:
        risk = Risk(run_id=run.id, title=title, description=description,
                    category=category if category in CATEGORIES else "security",
                    likelihood=min(max(likelihood, 1), 5), impact=min(max(impact, 1), 5), status="suggested", origin=origin)
        db.add(risk)
        await db.flush()
        for rid in dict.fromkeys(req_ids):
            db.add(RiskRequirement(risk_id=risk.id, requirement_version_id=rid))

    # Every template becomes an item, linked to its requirement. If the AI skipped one, use the template as written.
    adapted_a = {a.template_id: a for a in n.adapted_actions}
    for tid, (req, t) in action_slots.items():
        a = adapted_a.get(tid)
        default_priority = "high" if rating_of[req.key] <= 1 else "medium"
        await add_action(a.title if a else t["title"], a.description if a else t["description"],
                         a.priority if a else default_priority, "template", [req.id])
    adapted_k = {k.template_id: k for k in n.adapted_risks}
    for tid, (req, t) in risk_slots.items():
        k = adapted_k.get(tid)
        await add_risk(k.title if k else t["title"], k.description if k else t["description"], k.category if k else "security",
                       k.likelihood if k else 3, k.impact if k else 3, "template", [req.id])

    # Free AI writing only for gaps without a template: links to templated gaps are dropped, and an item left with
    # no gap to point at is skipped.
    free_a, free_k = set(free_action_keys), set(free_risk_keys)
    for a in n.action_items:
        ids = [scope.by_key[key].id for key in a.requirement_keys if key in free_a]
        if ids:
            await add_action(a.title, a.description, a.priority, "ai", ids)
    for k in n.risks:
        ids = [scope.by_key[key].id for key in k.requirement_keys if key in free_k]
        if ids:
            await add_risk(k.title, k.description, k.category, k.likelihood, k.impact, "ai", ids)

    by_name = {d.domain: d for d in n.domains}
    for rollup in (await db.execute(select(RunRollup).where(RunRollup.run_id == run.id))).scalars():
        if rollup.level == "assessment":
            rollup.explanation = n.overall_explanation
        elif rollup.level == "domain":
            d = by_name.get(r["domains"][rollup.ref_id]["name"])
            rollup.explanation = d.score_explanation if d else None

    content = {
        "title": version.title,
        "version": version.version,
        "company": {"name": tenant.name, "industry": tenant.industry, "employees": tenant.employee_count},
        "generated_at": now().isoformat(),
        "overall": {"score": r["overall"], "explanation": n.overall_explanation},
        "executive_summary": n.executive_summary,
        "frameworks": [{"name": f["name"], "pct": f["pct"], "covered": f["covered"], "considered": f["considered"]} for f in r["frameworks"].values()],
        "domains": [
            {
                "name": d.name,
                "score": r["domains"][d.avd_id]["score"],
                "weakest_link": r["domains"][d.avd_id]["weakest"],
                **({k: v for k, v in by_name[d.name].model_dump().items() if k != "domain"} if d.name in by_name else {}),
                "requirements": [
                    {"key": q.key, "control": q.control, "statement": q.statement,
                     "rating": None if q.id not in evals or evals[q.id].is_na else evals[q.id].rating,
                     "na": bool(q.id in evals and evals[q.id].is_na),
                     "rationale": evals[q.id].rationale if q.id in evals else None}
                    for q in d.requirements
                ],
            }
            for d in scope.domains
        ],
    }
    report = (await db.execute(select(Report).where(Report.run_id == run.id))).scalar_one_or_none()
    if report is None:
        report = Report(run_id=run.id, content=content, status="draft")
        db.add(report)
    report.content, report.status, report.generated_at = content, "draft", now()
    await db.flush()
    return {"actions": len(n.action_items), "risks": len(n.risks), "overall": r["overall"]}
