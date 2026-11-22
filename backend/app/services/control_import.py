"""Control library import: validate a workbook against the library, diff it, and apply it.

The preview never writes to the library. Apply re-runs the whole preview against the current state inside one
transaction, and refuses if anything moved since the preview (fingerprints) or any error appears."""

import difflib
import hashlib
import json
import uuid
from dataclasses import dataclass, field

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.library import (
    MAX_REQUIREMENTS,
    MULTI_FIELDS,
    TEXT_FIELDS,
    ControlIn,
    ControlVersionOut,
    RequirementIn,
    Template,
    _apply_fields,
    _next_control_code,
    _recode,
    _write_requirements,
    get_control,
    version_code,
)
from app.models import (
    Control,
    ControlVersion,
    Domain,
    DomainVersion,
    Framework,
    FrameworkClause,
    FrameworkVersion,
    MasterDataItem,
    OrganisationalRole,
    Requirement,
    RequirementVersion,
)
from app.services import versioning as v
from app.services.control_workbook import (
    CONTROL_COLS,
    REQUIREMENT_COLS,
    TEMPLATE_COLS,
    Lists,
    Parsed,
    Row,
    parse_workbook,
    split_lines,
    split_multi,
)

SINGLE_FIELDS = {"area": "area", "company_risk_exposure": "company_risk_exposure"}  # column key -> category
FIELD_LABELS = {
    "domain_id": "Domain", "title": "Title", "area_id": "Area", "company_risk_exposure_id": "Company risk exposure",
    "responsible_role_id": "Responsible role", "control_types": "Control types",
    "protection_domains": "Protection domains", "security_capabilities": "Security capabilities",
    "protection_objectives": "Protection objectives", "use_cases": "Use cases",
    "short_description": "Short description", "key_requirement": "Key requirement", "risk_exposure": "Risk exposure",
    "involved_parties": "Involved parties", "triggers": "Triggers", "supporting_documents": "Supporting documents",
    "special_considerations": "Special considerations", "subject_specific_support": "Subject-specific support",
}
REQ_LABELS = {"statement": "Statement", "guidance": "Guidance", "mandatory": "Mandatory", "evidence": "Evidence",
              "action_templates": "Action templates", "risk_templates": "Risk templates",
              "clause_ids": "Framework clauses"}
HEADERS = {"Controls": {c.key: c.header for c in CONTROL_COLS},
           "Requirements": {c.key: c.header for c in REQUIREMENT_COLS},
           "Templates": {c.key: c.header for c in TEMPLATE_COLS}}
AMBIGUOUS = object()


# ---------- what's in the library ----------


@dataclass
class Existing:
    id: uuid.UUID
    code: str
    domain_locked: bool
    published: ControlVersionOut | None
    draft: ControlVersionOut | None
    max_version: int
    draft_row_id: uuid.UUID | None = None

    @property
    def canon_published(self) -> dict | None:
        return canon_from_out(self.published) if self.published else None

    @property
    def canon_draft(self) -> dict | None:
        return canon_from_out(self.draft) if self.draft else None

    def fingerprint(self) -> str:
        payload = {"p": self.canon_published, "d": self.canon_draft, "pv": self.published and self.published.version,
                   "dv": self.draft and self.draft.version}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class Catalog:
    domains: dict[str, Domain]                          # abbreviation -> domain
    domain_names: dict[uuid.UUID, str]
    domain_published: set[uuid.UUID]
    master: dict[str, dict[str, object]]                # category -> lowercase label/code -> item | AMBIGUOUS
    master_by_id: dict[uuid.UUID, MasterDataItem]
    roles: dict[str, object]                            # lowercase name/abbreviation/code -> role | AMBIGUOUS
    role_by_id: dict[uuid.UUID, OrganisationalRole]
    frameworks: dict[str, dict | None]                  # FW code -> {ref lower: clause} for its published version
    clause_names: dict[uuid.UUID, str]                  # clause id -> "FW:ref"
    controls: dict[str, Existing]                       # code -> existing control
    requirements: dict[str, tuple[uuid.UUID, uuid.UUID]]  # requirement code -> (requirement id, control id)


def _index(items, keys) -> dict[str, object]:
    out: dict[str, object] = {}
    for item in items:
        for k in {x.strip().lower() for x in keys(item) if x}:
            out[k] = AMBIGUOUS if k in out and out[k] is not item else item
    return out


async def load_catalog(db: AsyncSession) -> Catalog:
    domains = (await db.execute(select(Domain))).scalars().all()
    dvs = (await db.execute(select(DomainVersion).where(DomainVersion.status.in_(("draft", "published"))))).scalars().all()
    names: dict[uuid.UUID, str] = {}
    for dv in sorted(dvs, key=lambda x: x.status != "published"):  # published name wins
        names.setdefault(dv.domain_id, dv.name)

    items = (await db.execute(select(MasterDataItem).order_by(MasterDataItem.sort_order))).scalars().all()
    master = {cat: _index([i for i in items if i.category == cat], lambda i: (i.label, i.code))
              for cat in {*SINGLE_FIELDS.values(), *MULTI_FIELDS.values()}}
    roles = (await db.execute(select(OrganisationalRole).order_by(OrganisationalRole.sort_order))).scalars().all()

    frameworks: dict[str, dict | None] = {}
    clause_names: dict[uuid.UUID, str] = {}
    for fw in (await db.execute(select(Framework))).scalars().all():
        frameworks[fw.code.upper()] = None
    rows = (await db.execute(
        select(FrameworkClause, Framework.code)
        .join(FrameworkVersion, FrameworkVersion.id == FrameworkClause.framework_version_id)
        .join(Framework, Framework.id == FrameworkVersion.framework_id)
        .where(FrameworkVersion.status == "published")
        .order_by(Framework.code, FrameworkClause.sort_order)
    )).all()
    for clause, fw_code in rows:
        frameworks.setdefault(fw_code.upper(), None)
        if frameworks[fw_code.upper()] is None:
            frameworks[fw_code.upper()] = {}
        frameworks[fw_code.upper()][clause.ref.lower()] = clause
        clause_names[clause.id] = f"{fw_code}:{clause.ref}"

    controls: dict[str, Existing] = {}
    for control in (await db.execute(select(Control).order_by(Control.code))).scalars().all():
        detail = await get_control(control.id, db, None)
        for out in (detail.published, detail.draft):
            for r in out.requirements if out else []:
                for c in r.clauses:
                    clause_names.setdefault(c.id, f"{c.framework_code}:{c.ref}")
        controls[control.code.upper()] = Existing(
            id=control.id, code=control.code, domain_locked=detail.domain_locked, published=detail.published,
            draft=detail.draft, max_version=max((x.version for x in detail.versions), default=0),
            draft_row_id=detail.draft.id if detail.draft else None,
        )
    reqs = (await db.execute(select(Requirement))).scalars().all()
    return Catalog(
        domains={d.abbreviation.upper(): d for d in domains}, domain_names=names,
        domain_published={dv.domain_id for dv in dvs if dv.status == "published"},
        master=master, master_by_id={i.id: i for i in items},
        roles=_index(roles, lambda r: (r.name, r.abbreviation, r.code)), role_by_id={r.id: r for r in roles},
        frameworks=frameworks, clause_names=clause_names, controls=controls,
        requirements={r.code.upper(): (r.id, r.control_id) for r in reqs},
    )


# ---------- canonical form (what is compared) ----------


def _tpl(items) -> list[dict]:
    return [{"title": t["title"] if isinstance(t, dict) else t.title,
             "description": t["description"] if isinstance(t, dict) else t.description} for t in items]


def canon_from_out(o: ControlVersionOut) -> dict:
    return {
        "domain_id": str(o.domain_id), "title": o.title,
        "area_id": str(o.area.id) if o.area else None,
        "company_risk_exposure_id": str(o.company_risk_exposure.id) if o.company_risk_exposure else None,
        "responsible_role_id": str(o.responsible_role.id) if o.responsible_role else None,
        **{f: sorted(str(x.id) for x in getattr(o, f)) for f in MULTI_FIELDS},
        **{f: getattr(o, f) for f in TEXT_FIELDS},
        "requirements": [
            {"requirement_id": str(r.requirement_id), "code": r.code, "statement": r.statement, "guidance": r.guidance,
             "mandatory": r.mandatory, "evidence": list(r.evidence), "action_templates": _tpl(r.action_templates),
             "risk_templates": _tpl(r.risk_templates), "clause_ids": sorted(str(c.id) for c in r.clauses)}
            for r in o.requirements
        ],
    }


def canon_from_in(body: ControlIn, codes: dict[str, str]) -> dict:
    """codes: requirement id -> code, for display."""
    return {
        "domain_id": str(body.domain_id), "title": body.title.strip(),
        "area_id": str(body.area_id) if body.area_id else None,
        "company_risk_exposure_id": str(body.company_risk_exposure_id) if body.company_risk_exposure_id else None,
        "responsible_role_id": str(body.responsible_role_id) if body.responsible_role_id else None,
        **{f: sorted({str(x) for x in getattr(body, f)}) for f in MULTI_FIELDS},
        **{f: (getattr(body, f) or "").strip() or None for f in TEXT_FIELDS},
        "requirements": [
            {"requirement_id": str(r.requirement_id) if r.requirement_id else None,
             "code": codes.get(str(r.requirement_id)) if r.requirement_id else None,
             "statement": r.statement.strip(), "guidance": r.guidance.strip(), "mandatory": r.mandatory,
             "evidence": [x.strip() for x in r.evidence if x.strip()],
             "action_templates": [{"title": t.title.strip(), "description": t.description.strip()} for t in r.action_templates],
             "risk_templates": [{"title": t.title.strip(), "description": t.description.strip()} for t in r.risk_templates],
             "clause_ids": sorted({str(c) for c in r.clause_ids})}
            for r in body.requirements
        ],
    }


def _same(a: dict, b: dict) -> bool:
    strip = lambda c: {**c, "requirements": [{k: v for k, v in r.items() if k != "code"} for r in c["requirements"]]}  # noqa: E731
    return strip(a) == strip(b)


# ---------- display ----------


def _show(cat: Catalog, key: str, value) -> str:
    if value in (None, [], ""):
        return ""
    if key == "domain_id":
        d = next((d for d in cat.domains.values() if str(d.id) == value), None)
        return d.abbreviation if d else value
    if key in ("area_id", "company_risk_exposure_id"):
        m = cat.master_by_id.get(uuid.UUID(value))
        return m.label if m else value
    if key == "responsible_role_id":
        r = cat.role_by_id.get(uuid.UUID(value))
        return r.name if r else value
    if key in MULTI_FIELDS:
        return "; ".join(sorted(cat.master_by_id[uuid.UUID(x)].label if uuid.UUID(x) in cat.master_by_id else x
                                for x in value))
    if key == "clause_ids":
        return "; ".join(sorted(cat.clause_names.get(uuid.UUID(x), x) for x in value))
    if key == "mandatory":
        return "Yes" if value else "No"
    if key == "evidence":
        return "\n".join(value)
    if key in ("action_templates", "risk_templates"):
        return "\n".join(f"{t['title']}: {t['description']}" for t in value)
    return str(value)


def diff(cat: Catalog, before: dict | None, after: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Field changes, requirement changes, and requirements that would be removed."""
    fields = []
    for key, label in FIELD_LABELS.items():
        b = before.get(key) if before else None
        if (b or None) != (after.get(key) or None):
            fields.append({"field": label, "before": _show(cat, key, b), "after": _show(cat, key, after.get(key))})

    old = {r["requirement_id"]: (i, r) for i, r in enumerate(before["requirements"])} if before else {}
    reqs = []
    seen = set()
    for i, r in enumerate(after["requirements"]):
        rid = r["requirement_id"]
        if rid is None or rid not in old:
            reqs.append({"code": None, "position": i + 1, "status": "added", "statement": r["statement"], "changes": []})
            continue
        seen.add(rid)
        j, o = old[rid]
        changes = [{"field": label, "before": _show(cat, k, o[k]), "after": _show(cat, k, r[k])}
                   for k, label in REQ_LABELS.items() if o[k] != r[k] and (o[k] or None) != (r[k] or None)]
        status = "changed" if changes else "moved" if i != j else "unchanged"
        reqs.append({"code": o["code"], "position": i + 1, "status": status, "statement": r["statement"],
                     "changes": changes, "moved_from": j + 1 if i != j else None})
    removed = [{"code": o["code"], "statement": o["statement"]}
               for rid, (_, o) in sorted(old.items(), key=lambda x: x[1][0]) if rid not in seen]
    return fields, reqs, removed


# ---------- validation ----------


@dataclass
class Entry:
    """One control row and everything that hangs off it."""
    row: Row
    ref: str
    existing: Existing | None
    invalid: bool = False
    fields: dict = field(default_factory=dict)
    requirements: list[dict] = field(default_factory=list)  # {"row", "requirement_id", "templates": {...}, ...}


@dataclass
class Result:
    issues: list[dict] = field(default_factory=list)
    controls: list[dict] = field(default_factory=list)       # report entries, in file order
    plans: list[dict] = field(default_factory=list)          # what apply does, in file order
    fingerprints: dict[str, str] = field(default_factory=dict)

    @property
    def errors(self) -> int:
        return sum(1 for i in self.issues if i["level"] == "error")

    def summary(self) -> dict:
        count = lambda s: sum(1 for c in self.controls if c["status"] == s)  # noqa: E731
        return {"new": count("new"), "changed": count("changed"), "unchanged": count("unchanged"),
                "conflicts": count("conflict"), "invalid": count("invalid"), "errors": self.errors,
                "warnings": len(self.issues) - self.errors,
                "removals": sum(len(c["removals"]) for c in self.controls)}

    def report(self) -> dict:
        return {"issues": self.issues, "controls": self.controls}


class Checker:
    def __init__(self, cat: Catalog, result: Result):
        self.cat, self.result = cat, result

    def issue(self, level: str, row: Row | None, key: str | None, message: str, suggestion: str | None = None,
              entry: Entry | None = None, value: str | None = None) -> None:
        self.result.issues.append({
            "level": level, "sheet": row.sheet if row else None, "row": row.row if row else None,
            "column": HEADERS[row.sheet].get(key) if row and key else None,
            "value": value if value is not None else (row.values.get(key) if row and key else None),
            "message": message, "suggestion": suggestion,
            "control": entry.ref if entry else None,
        })
        if level == "error" and entry:
            entry.invalid = True

    def error(self, row, key, message, suggestion=None, entry=None, value=None):
        self.issue("error", row, key, message, suggestion, entry, value)

    @staticmethod
    def suggest(value: str, options: list[str]) -> str | None:
        lowered = {o.lower(): o for o in options}
        match = difflib.get_close_matches(value.lower(), list(lowered), n=1, cutoff=0.55)
        return lowered[match[0]] if match else None

    def lookup(self, index: dict[str, object], value: str, what: str, row: Row, key: str, entry: Entry,
               display) -> object | None:
        item = index.get(value.lower())
        if item is AMBIGUOUS:
            self.error(row, key, f"“{value}” matches more than one {what}. Use its code instead.", entry=entry, value=value)
            return None
        if item is None:
            options = sorted({display(i) for i in index.values() if i is not AMBIGUOUS})
            self.error(row, key, f"No {what} called “{value}”. Add it in master data first, or pick one from the "
                       "Lists sheet.", self.suggest(value, options), entry=entry, value=value)
            return None
        if not item.is_active:
            self.error(row, key, f"The {what} “{value}” is switched off. Switch it on in master data or pick another.",
                       entry=entry, value=value)
            return None
        return item

    def text(self, row: Row, key: str, entry: Entry, label: str, lo: int = 0, hi: int | None = None,
             required: bool = False) -> str:
        value = row.values.get(key, "")
        if required and not value:
            self.error(row, key, f"{label} is required.", entry=entry)
        elif value and len(value) < lo:
            self.error(row, key, f"{label} needs at least {lo} characters.", entry=entry)
        elif hi and len(value) > hi:
            self.error(row, key, f"{label} is {len(value)} characters; the limit is {hi}.", entry=entry,
                       value=value[:80] + "…")
        return value


def _base_version(code: str, value: str) -> int | None | str:
    """'IAM02.0003' -> 3; '' -> None; anything else -> 'bad'."""
    if not value:
        return None
    prefix, _, number = value.rpartition(".")
    if prefix.upper() != code.upper() or not number.isdigit():
        return "bad"
    return int(number)


async def preview(db: AsyncSession, data: bytes) -> Result:
    result = Result()
    parsed: Parsed = parse_workbook(data)
    if parsed.error:
        result.issues.append({"level": "error", "sheet": None, "row": None, "column": None, "value": None,
                              "message": parsed.error, "suggestion": None, "control": None})
        return result
    cat = await load_catalog(db)
    ck = Checker(cat, result)

    # --- Controls sheet ---
    entries: dict[str, Entry] = {}
    ordered: list[Entry] = []
    for row in parsed.controls:
        vals = row.values
        code, key = vals.get("code", "").upper(), vals.get("key", "")
        existing = cat.controls.get(code) if code else None
        ref = code or key.upper()
        entry = Entry(row=row, ref=code or key, existing=existing)
        if code and existing is None:
            ck.error(row, "code", f"There's no control {code}. Codes are assigned by the app: leave this blank to "
                     "create a new control.", entry=entry)
        if not code and not key:
            ck.error(row, "key", "A new control needs an import key (any short text, e.g. N1) so its requirements "
                     "can point to it.", entry=entry)
        elif not code and key.upper() in cat.controls:
            ck.error(row, "key", f"“{key}” is an existing control code. Put it in Control code to update that control, "
                     "or pick another import key.", entry=entry)
        if ref and ref in entries:
            ck.error(row, "code" if code else "key", f"{entry.ref} appears twice in the Controls sheet (row "
                     f"{entries[ref].row.row}).", entry=entry)
        elif ref:
            entries[ref] = entry
        ordered.append(entry)

        f: dict = {}
        abbr = vals.get("domain", "").upper()
        domain = cat.domains.get(abbr)
        if not abbr:
            ck.error(row, "domain", "Domain is required.", entry=entry)
        elif domain is None:
            ck.error(row, "domain", f"No domain {abbr}. Create it in the control library first.",
                     ck.suggest(abbr, list(cat.domains)), entry=entry)
        f["domain_id"] = domain.id if domain else None
        f["title"] = ck.text(row, "title", entry, "Title", 2, 300, required=True)
        for col, category in SINGLE_FIELDS.items():
            value = vals.get(col, "")
            item = ck.lookup(cat.master[category], value, category.replace("_", " ") + " value", row, col, entry,
                             lambda i: i.label) if value else None
            f[f"{col}_id"] = item.id if item else None
        role_name = vals.get("responsible_role", "")
        role = ck.lookup(cat.roles, role_name, "organisational role", row, "responsible_role", entry,
                         lambda r: r.name) if role_name else None
        f["responsible_role_id"] = role.id if role else None
        for col, category in MULTI_FIELDS.items():
            ids = []
            for value in split_multi(vals.get(col, "")):
                item = ck.lookup(cat.master[category], value, category.replace("_", " ") + " value", row, col, entry,
                                 lambda i: i.label)
                if item:
                    ids.append(item.id)
            f[col] = list(dict.fromkeys(ids))
        for col in TEXT_FIELDS:
            f[col] = vals.get(col) or None
        entry.fields = f

        if existing:
            base = _base_version(existing.code, vals.get("base", ""))
            current = existing.published.version if existing.published else None
            if base == "bad":
                ck.error(row, "base", f"Base version should look like {version_code(existing.code, 1)}. Don't edit "
                         "this column; export again if unsure.", entry=entry)
            elif base is None:
                ck.issue("warning", row, "base", "No base version, so the import can't tell whether someone published "
                         "this control after your copy was made.", entry=entry)
            elif current and base < current:
                ck.error(row, "base", f"Stale: your row is based on {version_code(existing.code, base)}, but "
                         f"{version_code(existing.code, current)} has been published since. Export again and redo "
                         "your edits on the new file.", entry=entry)
            if domain and existing.domain_locked:
                locked_to = (existing.published or existing.draft).domain_id
                if domain.id != locked_to:
                    ck.error(row, "domain", "The domain is part of the control code, so it can't change once the "
                             "control has been published.", entry=entry)

    # --- Requirements sheet ---
    req_refs: dict[str, dict] = {}
    for row in parsed.requirements:
        vals = row.values
        cref = vals.get("control", "").upper()
        entry = entries.get(cref)
        if not cref:
            ck.error(row, "control", "Say which control this requirement belongs to (its code or import key).")
            continue
        if entry is None:
            msg = (f"{cref} isn't in the Controls sheet. Add its row (export it from the library), or remove these "
                   "requirements." if cref in cat.controls else f"No control {cref} in the Controls sheet.")
            ck.error(row, "control", msg, ck.suggest(cref, list(entries)) if cref not in cat.controls else None)
            continue
        req: dict = {"row": row, "entry": entry, "requirement_id": None, "action_templates": [],
                     "risk_templates": []}
        rcode, rkey = vals.get("code", "").upper(), vals.get("key", "").upper()
        if rcode:
            known = cat.requirements.get(rcode)
            if known is None:
                ck.error(row, "code", f"There's no requirement {rcode}. Leave this blank for a new requirement.",
                         entry=entry)
            elif entry.existing is None or known[1] != entry.existing.id:
                ck.error(row, "code", f"{rcode} belongs to another control. Requirements can't move between controls.",
                         entry=entry)
            else:
                req["requirement_id"] = known[0]
            if rcode in req_refs:
                ck.error(row, "code", f"{rcode} appears twice (row {req_refs[rcode]['row'].row}).", entry=entry)
            else:
                req_refs[rcode] = req
        elif rkey:
            if rkey in req_refs:
                ck.error(row, "key", f"Import key {vals['key']} is used twice (row {req_refs[rkey]['row'].row}).",
                         entry=entry)
            elif rkey in cat.requirements:
                ck.error(row, "key", f"“{vals['key']}” is an existing requirement code. Put it in Requirement code, "
                         "or pick another import key.", entry=entry)
            else:
                req_refs[rkey] = req
        req["statement"] = ck.text(row, "statement", entry, "Statement", 5, required=True)
        req["guidance"] = ck.text(row, "guidance", entry, "Guidance", 5, 1000, required=True)
        mandatory = vals.get("mandatory", "").lower()
        if mandatory in ("yes", "y", "true", "1"):
            req["mandatory"] = True
        elif mandatory in ("no", "n", "false", "0"):
            req["mandatory"] = False
        elif mandatory:
            ck.error(row, "mandatory", "Mandatory must be Yes, No or blank.", entry=entry)
            req["mandatory"] = None
        else:
            req["mandatory"] = None
        req["evidence"] = split_lines(vals.get("evidence", ""))
        clause_ids = []
        for value in split_multi(vals.get("clauses", "")):
            fw, sep, ref = value.partition(":")
            fw, ref = fw.strip().upper(), ref.strip()
            if not sep or not fw or not ref:
                ck.error(row, "clauses", f"Write clauses as FRAMEWORK:ref (e.g. ISO27001:A.5.15), not “{value}”.",
                         entry=entry, value=value)
            elif fw not in cat.frameworks:
                ck.error(row, "clauses", f"No framework {fw}.", ck.suggest(fw, list(cat.frameworks)), entry=entry,
                         value=value)
            elif cat.frameworks[fw] is None:
                ck.error(row, "clauses", f"{fw} has no published version, so its clauses can't be linked yet.",
                         entry=entry, value=value)
            elif ref.lower() not in cat.frameworks[fw]:
                refs = [c.ref for c in cat.frameworks[fw].values()]
                hint = ck.suggest(ref, refs)
                ck.error(row, "clauses", f"{fw} has no clause {ref}.", f"{fw}:{hint}" if hint else None, entry=entry,
                         value=value)
            else:
                clause_ids.append(cat.frameworks[fw][ref.lower()].id)
        req["clause_ids"] = list(dict.fromkeys(clause_ids))
        entry.requirements.append(req)

    # --- Templates sheet ---
    for row in parsed.templates:
        vals = row.values
        rref = vals.get("requirement", "").upper()
        target = req_refs.get(rref)
        if not rref:
            ck.error(row, "requirement", "Say which requirement this template belongs to (its code or import key).")
            continue
        if target is None:
            if rref in cat.requirements:
                ck.error(row, "requirement", f"{rref} isn't in the Requirements sheet. If you're removing it, delete "
                         "its template rows too; otherwise add the requirement's row back.")
            else:
                ck.error(row, "requirement", f"No requirement {rref} in the Requirements sheet.",
                         ck.suggest(rref, list(req_refs)))
            continue
        entry = target["entry"]
        kind = vals.get("kind", "").lower()
        if kind not in ("action", "risk"):
            ck.error(row, "kind", "Kind must be Action or Risk.", entry=entry)
        title = ck.text(row, "title", entry, "Template title", 2, 300, required=True)
        description = ck.text(row, "description", entry, "Template description", 2, 4000, required=True)
        if kind in ("action", "risk") and title and description:
            target[f"{kind}_templates"].append({"title": title, "description": description})

    # --- per control: counts, diff, plan ---
    used: dict[str, set[int]] = {}
    for code in cat.controls:
        for abbr in cat.domains:
            if code.startswith(abbr) and code[len(abbr):].isdigit():
                used.setdefault(abbr, set()).add(int(code[len(abbr):]))

    for entry in ordered:
        row = entry.row
        n = len(entry.requirements)
        if n == 0:
            ck.error(row, "code" if row.values.get("code") else "key", f"{entry.ref or 'This control'} has no requirements in "
                     "the Requirements sheet.", entry=entry)
        elif n > MAX_REQUIREMENTS:
            ck.error(row, "code" if row.values.get("code") else "key", f"{entry.ref} has {n} requirements; the limit is "
                     f"{MAX_REQUIREMENTS}.", entry=entry)
        domain = next((d for d in cat.domains.values() if d.id == entry.fields.get("domain_id")), None)

        report = {"ref": entry.ref, "row": row.row, "code": entry.existing.code if entry.existing else None,
                  "expected_code": None, "title": entry.fields.get("title") or "",
                  "domain": domain.abbreviation if domain else row.values.get("domain", ""),
                  "status": "invalid", "has_draft": bool(entry.existing and entry.existing.draft),
                  "base": None, "fields": [], "requirements": [], "removals": [], "publish_missing": []}
        result.controls.append(report)
        if entry.existing:
            result.fingerprints[entry.existing.code] = entry.existing.fingerprint()
        if entry.invalid:
            continue

        try:
            body = ControlIn(
                **entry.fields,
                requirements=[RequirementIn(
                    requirement_id=r["requirement_id"], statement=r["statement"], guidance=r["guidance"],
                    mandatory=r["mandatory"], evidence=r["evidence"],
                    action_templates=[Template(**t) for t in r["action_templates"]],
                    risk_templates=[Template(**t) for t in r["risk_templates"]], clause_ids=r["clause_ids"],
                ) for r in entry.requirements],
            )
        except ValidationError as e:  # the checks above should catch everything; this is the safety net
            ck.error(row, None, "This control didn't pass validation: " + "; ".join(x["msg"] for x in e.errors()),
                     entry=entry)
            continue

        codes = {}
        if entry.existing:
            for out in (entry.existing.published, entry.existing.draft):
                for r in out.requirements if out else []:
                    codes[str(r.requirement_id)] = r.code
        after = canon_from_in(body, codes)
        published = entry.existing.canon_published if entry.existing else None
        draft = entry.existing.canon_draft if entry.existing else None

        if entry.existing is None:
            status, base = "new", None
            prefix = domain.abbreviation.upper()
            taken = used.setdefault(prefix, set())
            number = next((i for i in range(1, 100) if i not in taken), None)
            if number is None:
                ck.error(row, "domain", f"Domain {prefix} already has 99 controls.", entry=entry)
                continue
            taken.add(number)
            report["expected_code"] = f"{domain.abbreviation}{number:02d}"
        elif (published and _same(published, after)) or (draft and _same(draft, after)):
            status, base = "unchanged", None
        elif draft:
            status, base = "conflict", draft
            report["base"] = entry.existing.draft.version_code
        else:
            status, base = "changed", published
            report["base"] = entry.existing.published.version_code
        report["status"] = status
        if status != "unchanged":
            report["fields"], report["requirements"], report["removals"] = diff(cat, base, after)
            missing = _missing(after)
            report["publish_missing"] = missing
            if missing:
                ck.issue("warning", row, None, "Imported as a draft, but it can't be published until these are filled "
                         "in: " + ", ".join(missing) + ".", entry=entry)
            if domain and domain.id not in cat.domain_published:
                ck.issue("warning", row, "domain", f"Domain {domain.abbreviation} isn't published yet, so this control "
                         "can't be published until it is.", entry=entry)
        result.plans.append({"ref": entry.ref, "status": status, "existing": entry.existing, "body": body})
    return result


def _missing(c: dict) -> list[str]:
    labels = {"control_types": "Control type", "protection_domains": "Protection domain",
              "security_capabilities": "Security capability", "protection_objectives": "Protection objective",
              "use_cases": "Use case"}
    out = []
    if not c["area_id"]:
        out.append("Area")
    if not c["responsible_role_id"]:
        out.append("Organisational role")
    out += [label for f, label in labels.items() if not c[f]]
    if not c["key_requirement"]:
        out.append("Key requirement")
    return out


# ---------- choices and apply ----------


def blockers(summary_controls: list[dict], issues: list[dict], choices: dict) -> list[str]:
    """Why the import can't be applied yet (empty = it can)."""
    out = []
    errors = sum(1 for i in issues if i["level"] == "error")
    if errors:
        out.append(f"{errors} error{'s' if errors != 1 else ''} to fix in the file")
    conflicts = choices.get("conflicts", {})
    ticked = set(choices.get("removals", []))
    undecided = [c["code"] for c in summary_controls if c["status"] == "conflict" and c["code"] not in conflicts]
    if undecided:
        out.append("Choose overwrite or skip for " + ", ".join(undecided))
    unticked = [r["code"] for c in summary_controls if c["status"] in ("changed", "conflict")
                and conflicts.get(c["code"]) != "skip" for r in c["removals"] if r["code"] not in ticked]
    if unticked:
        out.append("Confirm the removal of " + ", ".join(unticked))
    if not errors and not undecided and not any(
            c["status"] in ("new", "changed") or (c["status"] == "conflict" and conflicts.get(c["code"]) == "overwrite")
            for c in summary_controls):
        out.append("Nothing to import: every control matches the library")
    return out


async def apply(db: AsyncSession, data: bytes, import_id: uuid.UUID, fingerprints: dict, choices: dict) -> dict:
    """Writes the import. Raises 409 (nothing written) when the library moved since the preview."""
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('control-import'))"))
    result = await preview(db, data)
    if result.errors:
        raise HTTPException(409, "The library changed since the preview and the file now has errors. Preview again.")
    if result.fingerprints != fingerprints:
        changed = sorted(k for k in {*result.fingerprints, *fingerprints} if result.fingerprints.get(k) != fingerprints.get(k))
        raise HTTPException(409, "These controls were changed in the library after the preview: " + ", ".join(changed)
                            + ". Preview again.")
    still = blockers(result.controls, result.issues, choices)
    if still:
        raise HTTPException(409, "; ".join(still))

    created, updated = [], []
    conflicts = choices.get("conflicts", {})
    for plan in result.plans:
        body: ControlIn = plan["body"]
        existing: Existing | None = plan["existing"]
        status = plan["status"]
        if status == "unchanged" or (status == "conflict" and conflicts.get(existing.code) != "overwrite"):
            continue
        if status == "new":
            control = Control(code=await _next_control_code(db, body.domain_id))
            db.add(control)
            await db.flush()
            cv = ControlVersion(control_id=control.id, version=1, status="draft", domain_id=body.domain_id,
                                title=body.title, import_id=import_id)
            db.add(cv)
            await db.flush()
            created.append(control.code)
        else:
            control = await db.get(Control, existing.id)
            if status == "changed":
                cv = ControlVersion(control_id=control.id, status="draft", domain_id=body.domain_id, title=body.title,
                                    version=await v.next_version_number(db, ControlVersion, "control_id", control.id),
                                    import_id=import_id)
                db.add(cv)
                await db.flush()
            else:  # overwrite the existing draft
                cv = await db.get(ControlVersion, existing.draft_row_id)
                if body.domain_id != cv.domain_id:
                    await _recode(db, control, body.domain_id)
                await db.execute(delete(RequirementVersion).where(RequirementVersion.control_version_id == cv.id))
                cv.import_id = import_id
                await db.flush()
            updated.append(control.code)
        await _apply_fields(db, cv, body)
        await _write_requirements(db, control, cv, body.requirements)
    return {"created": created, "updated": updated}


# ---------- lists for the template / export ----------


async def workbook_lists(db: AsyncSession) -> Lists:
    domains = (await db.execute(select(Domain).order_by(Domain.abbreviation))).scalars().all()
    cat = await load_catalog_lists(db)
    return Lists(
        domains=[(d.abbreviation, cat["names"].get(d.id, "")) for d in domains],
        master=cat["master"], roles=cat["roles"], clauses=cat["clauses"],
    )


async def load_catalog_lists(db: AsyncSession) -> dict:
    dvs = (await db.execute(select(DomainVersion).where(DomainVersion.status.in_(("draft", "published"))))).scalars().all()
    names: dict[uuid.UUID, str] = {}
    for dv in sorted(dvs, key=lambda x: x.status != "published"):
        names.setdefault(dv.domain_id, dv.name)
    items = (await db.execute(select(MasterDataItem).where(MasterDataItem.is_active)
                              .order_by(MasterDataItem.sort_order, MasterDataItem.label))).scalars().all()
    by_col = {**{k: c for k, c in SINGLE_FIELDS.items()}, **MULTI_FIELDS}
    master = {col: [(i.label, i.code) for i in items if i.category == cat] for col, cat in by_col.items()}
    roles = (await db.execute(select(OrganisationalRole).where(OrganisationalRole.is_active)
                              .order_by(OrganisationalRole.sort_order))).scalars().all()
    clauses = (await db.execute(
        select(FrameworkClause, Framework.code)
        .join(FrameworkVersion, FrameworkVersion.id == FrameworkClause.framework_version_id)
        .join(Framework, Framework.id == FrameworkVersion.framework_id)
        .where(FrameworkVersion.status == "published")
        .order_by(Framework.code, FrameworkClause.sort_order)
    )).all()
    return {"names": names, "master": master, "roles": [(r.name, r.abbreviation) for r in roles],
            "clauses": [(f"{fw}:{c.ref}", c.title) for c, fw in clauses]}


def export_rows(outs: list[tuple[str, ControlVersionOut]], domain_abbr: dict[uuid.UUID, str]):
    """(control code, version) pairs -> rows for the three sheets."""
    controls, requirements, templates = [], [], []
    join = lambda xs: "; ".join(x.label for x in xs)  # noqa: E731
    for code, o in outs:
        controls.append({
            "code": code, "base": o.version_code, "domain": domain_abbr.get(o.domain_id, ""), "title": o.title,
            "area": o.area.label if o.area else None,
            "company_risk_exposure": o.company_risk_exposure.label if o.company_risk_exposure else None,
            "responsible_role": o.responsible_role.name if o.responsible_role else None,
            **{f: join(getattr(o, f)) for f in MULTI_FIELDS}, **{f: getattr(o, f) for f in TEXT_FIELDS},
        })
        for r in o.requirements:
            requirements.append({
                "control": code, "code": r.code, "statement": r.statement, "guidance": r.guidance,
                "mandatory": "Yes" if r.mandatory else "No" if r.mandatory is False else None,
                "evidence": "\n".join(r.evidence), "clauses": "; ".join(f"{c.framework_code}:{c.ref}" for c in r.clauses),
            })
            for kind, items in (("Action", r.action_templates), ("Risk", r.risk_templates)):
                for t in items:
                    templates.append({"requirement": r.code, "kind": kind, "title": t.title, "description": t.description})
    return controls, requirements, templates
