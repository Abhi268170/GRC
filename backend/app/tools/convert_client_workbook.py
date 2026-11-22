"""Converts the client's control workbook into a TrustUp control import file.

The client's layout (tab "360TrustUP Controls") has one wide row per control, with up to ten
blocks of requirement columns. The app's import expects three sheets (Controls, Requirements,
Templates; see CONTROL_IMPORT_PLAN.md). This tool only converts: the result still goes through
the normal import screen, with its preview and checks.

Usage (reads the workbook on stdin, writes the import file on stdout, the report on stderr):

    docker compose exec -T backend python -m app.tools.convert_client_workbook \\
        < "client workbook.xlsx" > controls-import.xlsx 2> controls-import-report.md

What it does:
- Every control is new: "Control code" stays blank and the workbook's Control ID (IM01.0001)
  becomes the import key. The app assigns codes in row order, so rows are sorted by Control ID.
- Domains are matched by name. Master data values and roles are passed through as written.
- Framework mappings ("ISO 27001:2022 5.15 Access control; NIST CSF 2.0 PR.AA-05 ...") become
  FRAMEWORK:ref. A reference that doesn't exist in the app's frameworks is left out and listed
  in the report; so is every reference whose title differs from the official one.
- Not converted: Control Language, Domain Question, Roles, the notes above the header row, and
  anything in "Company risk exposure" that isn't one of the app's values."""

import asyncio
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import select

from app.core.db import ControlSession, dispose_all
from app.models import Framework, FrameworkClause, FrameworkVersion
from app.services import control_import
from app.services.control_workbook import MULTI_SEP, build_workbook

SHEET = "360TrustUP Controls"

# Client column header -> import column key.
CONTROL_FIELDS = {
    "title": "title", "area": "area", "company risk exposure": "company_risk_exposure",
    "responsible role": "responsible_role", "accountable role": "responsible_role",
    "control type": "control_types", "protection domain": "protection_domains",
    "security capability": "security_capabilities", "protection objective": "protection_objectives",
    "use case": "use_cases", "short description": "short_description", "key requirement": "key_requirement",
    "risk exposure (informational)": "risk_exposure", "involved parties": "involved_parties", "triggers": "triggers",
    "supporting documents": "supporting_documents", "special considerations": "special_considerations",
    "subject-specific support": "subject_specific_support",
}
MULTI = {"control_types", "protection_domains", "security_capabilities", "protection_objectives", "use_cases"}
SKIPPED = ("control language", "domain question", "roles")
# Requirement block column ("Requirements #3 Risks Title") -> field.
REQ_FIELDS = {
    "statement": "statement", "guidance": "guidance", "framework mappings": "clauses", "evidence": "evidence",
    "action item title": "action_title", "action item description": "action_description",
    "risk title": "risk_title", "risks title": "risk_title", "risk description": "risk_description",
    "risks description": "risk_description",
}

# How the workbook writes a reference -> (framework code, ref). Order matters: first match wins.
MAPPING_PATTERNS = [
    (re.compile(r"^ISO 27001:2022 Clause (\d+(?:\.\d+)*)\b\s*(.*)$"), "ISO-27001", "{0}"),
    (re.compile(r"^ISO 27001:2022 (?:Annex )?A?\.?\s?(\d+\.\d+)\b\s*(.*)$"), "ISO-27001", "A.{0}"),
    (re.compile(r"^ISO 27005:2022 Clause (\d+(?:\.\d+)*)\b\s*(.*)$"), "ISO-27005", "{0}"),
    (re.compile(r"^NIST CSF 2\.0 ([A-Z]{2}\.[A-Z]{2}-\d{2})\b\s*(.*)$"), "NIST-CSF", "{0}"),
    (re.compile(r"^GDPR(?: \(EU 2016/679\))? Art\. ?(\d+)\b\s*(.*)$"), "GDPR", "Art. {0}"),
    (re.compile(r"^Swiss FADP:2023 \(DPO\) Art\. ?(\d+[a-z]?)\b\s*(.*)$"), "CH-DPO", "Art. {0}"),
    (re.compile(r"^Swiss FADP:2023 Art\. ?(\d+[a-z]?)\b\s*(.*)$"), "CH-FADP", "Art. {0}"),
]


def norm(value) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip() if value is not None else ""


def key(value) -> str:
    """For comparing names and titles: case, punctuation and spacing don't count."""
    return re.sub(r"[^a-z0-9]+", " ", norm(value).lower()).strip()


@dataclass
class Clause:
    ref: str
    title: str
    assessable: bool
    parent_title: str | None


@dataclass
class Report:
    unknown: list[tuple[str, str]] = field(default_factory=list)         # (requirement, reference as written)
    title_differs: list[tuple[str, str, str, str]] = field(default_factory=list)  # (requirement, FW:ref, written, official)
    paragraphs: list[tuple[str, str, str]] = field(default_factory=list)  # (requirement, FW:ref, "(1)(f) Integrity ...")
    headings: Counter = field(default_factory=Counter)                  # FW:ref mapped although it's only a heading
    notes: list[str] = field(default_factory=list)
    mapped: Counter = field(default_factory=Counter)                    # per framework


async def load_clauses(db) -> dict[str, dict[str, Clause]]:
    rows = (await db.execute(
        select(FrameworkClause, Framework.code)
        .join(FrameworkVersion, FrameworkVersion.id == FrameworkClause.framework_version_id)
        .join(Framework, Framework.id == FrameworkVersion.framework_id)
        .where(FrameworkVersion.status == "published"))).all()
    titles = {c.id: c.title for c, _ in rows}
    out: dict[str, dict[str, Clause]] = {}
    for c, code in rows:
        out.setdefault(code, {})[c.ref.lower()] = Clause(c.ref, c.title, c.is_assessable, titles.get(c.parent_id))
    return out


def convert_mappings(text: str, where: str, clauses: dict[str, dict[str, Clause]], report: Report) -> str:
    out: list[str] = []
    for written in (norm(x) for x in str(text or "").split(MULTI_SEP)):
        if not written:
            continue
        for pattern, framework, ref_format in MAPPING_PATTERNS:
            m = pattern.match(written)
            if m:
                break
        else:
            report.unknown.append((where, written))
            continue
        ref, written_title = ref_format.format(m.group(1)), m.group(2)
        clause = clauses.get(framework, {}).get(ref.lower())
        if clause is None:
            report.unknown.append((where, written))
            continue
        name = f"{framework}:{clause.ref}"
        # NIST subcategories have no title of their own; the workbook writes the category name.
        official = clause.parent_title if framework == "NIST-CSF" else clause.title
        if written_title.startswith("("):
            # "Art. 5 (1)(f) Integrity and confidentiality": a paragraph of the article. The app links whole articles.
            report.paragraphs.append((where, name, written_title))
        elif written_title and key(written_title) != key(official):
            report.title_differs.append((where, name, written_title, official or ""))
        if not clause.assessable:
            report.headings[name] += 1
        if name not in out:
            out.append(name)
            report.mapped[framework] += 1
    return f"{MULTI_SEP} ".join(out)


def read_sheet(data: bytes):
    wb = load_workbook(BytesIO(data), data_only=True)
    if SHEET not in wb.sheetnames:
        raise SystemExit(f'The workbook has no "{SHEET}" tab. Tabs: {", ".join(wb.sheetnames)}')
    ws = wb[SHEET]
    header_row = next((r for r in range(1, 30) if any(key(c.value) == "control id" for c in ws[r])), None)
    if header_row is None:
        raise SystemExit('No header row with a "Control ID" column in the first 30 rows.')
    headers = {i: norm(c.value) for i, c in enumerate(ws[header_row]) if norm(c.value)}
    rows = [r for r in ws.iter_rows(min_row=header_row + 1, values_only=True)]
    return headers, rows


async def convert(data: bytes) -> tuple[bytes, Report, dict]:
    report = Report()
    headers, rows = read_sheet(data)
    column = {key(h): i for i, h in headers.items()}
    blocks: dict[int, dict[str, int]] = {}
    for i, h in headers.items():
        m = re.match(r"requirements? #(\d+) (.+)$", h, flags=re.I)
        if m and key(m.group(2)) in REQ_FIELDS:
            blocks.setdefault(int(m.group(1)), {})[REQ_FIELDS[key(m.group(2))]] = i
    known = {"control id", "domain", *(key(h) for h in CONTROL_FIELDS), *SKIPPED}
    ignored = [h for i, h in headers.items() if key(h) not in known and not re.match(r"requirements? #\d+ ", h, flags=re.I)]
    if ignored:
        report.notes.append("Columns not recognised and left out: " + ", ".join(ignored))
    report.notes.append("Columns left out on purpose: " + ", ".join(headers[column[k]] for k in SKIPPED if k in column))

    async with ControlSession() as db:
        lists = await control_import.workbook_lists(db)
        clauses = await load_clauses(db)
    domain_by_name = {key(name): abbreviation for abbreviation, name in lists.domains}
    risk_values = {key(label) for label, _ in lists.master.get("company_risk_exposure", [])}

    def cell(row, name: str) -> str:
        i = column.get(name)
        return norm(row[i]) if i is not None and i < len(row) else ""

    source = [r for r in rows if cell(r, "control id")]
    domain_order = {d: n for n, d in enumerate(dict.fromkeys(cell(r, "domain") for r in source))}
    source.sort(key=lambda r: (domain_order[cell(r, "domain")], cell(r, "control id")))

    controls, requirements, templates = [], [], []
    for row in source:
        control_id = cell(row, "control id")
        domain = cell(row, "domain")
        abbreviation = domain_by_name.get(key(domain))
        if abbreviation is None:
            report.notes.append(f"{control_id}: domain “{domain}” isn't in the app; the import will ask for it.")
        out = {"key": control_id, "domain": abbreviation or domain}
        for header, field_key in CONTROL_FIELDS.items():
            value = cell(row, key(header))
            if not value or field_key in out:
                continue
            if field_key in MULTI:
                value = f"{MULTI_SEP} ".join(norm(v) for v in value.split(MULTI_SEP) if norm(v))
            out[field_key] = value
        if out.get("company_risk_exposure") and key(out["company_risk_exposure"]) not in risk_values:
            report.notes.append(f"{control_id}: “Company risk exposure” holds a note, not a value; left blank.")
            out.pop("company_risk_exposure")
        controls.append(out)

        for n in sorted(blocks):
            block = {f: norm(row[i]) if i < len(row) and row[i] is not None else "" for f, i in blocks[n].items()}
            if not block.get("statement"):
                if any(block.values()):
                    report.notes.append(f"{control_id} requirement #{n}: has content but no statement; left out.")
                continue
            req_key = f"{control_id}-R{n}"
            raw_evidence = row[blocks[n]["evidence"]] if "evidence" in blocks[n] else ""
            evidence = [re.sub(r"^[-•*]\s*", "", norm(line)) for line in str(raw_evidence or "").splitlines() if norm(line)]
            raw_clauses = row[blocks[n]["clauses"]] if "clauses" in blocks[n] else ""
            requirements.append({
                "control": control_id, "key": req_key, "statement": block["statement"], "guidance": block.get("guidance", ""),
                "evidence": "\n".join(evidence), "clauses": convert_mappings(raw_clauses, req_key, clauses, report),
            })
            for kind in ("action", "risk"):
                title, description = block.get(f"{kind}_title", ""), block.get(f"{kind}_description", "")
                if title or description:
                    templates.append({"requirement": req_key, "kind": kind.capitalize(), "title": title, "description": description})

    totals = {"controls": len(controls), "requirements": len(requirements), "templates": len(templates),
              "mappings": sum(report.mapped.values())}
    return build_workbook(lists, controls, requirements, templates, exported_by="convert_client_workbook"), report, totals


def _where(places: list[str]) -> str:
    return ", ".join(places[:4]) + (f" and {len(places) - 4} more" if len(places) > 4 else "")


def render(report: Report, totals: dict) -> str:
    lines = ["# Control workbook conversion report", "",
             f"- Controls: {totals['controls']}", f"- Requirements: {totals['requirements']}",
             f"- Action and risk templates: {totals['templates']}",
             f"- Framework mappings converted: {totals['mappings']} ("
             + ", ".join(f"{fw} {n}" for fw, n in sorted(report.mapped.items())) + ")",
             f"- References left out because they don't exist in the framework: {len(report.unknown)}",
             f"- References whose title differs from the official title: {len(report.title_differs)}",
             f"- References to a paragraph of an article, linked to the whole article: {len(report.paragraphs)}",
             f"- References to a heading that groups other clauses: {sum(report.headings.values())}", "",
             "This check only compares each reference with the official list of clauses and titles. It can't tell "
             "whether a clause is the right one for its requirement.", ""]
    if report.notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in report.notes] + [""]
    if report.unknown:
        lines += ["## References left out (not in the framework, or not in a recognised form)", "",
                  "| Requirement | Reference as written |", "|---|---|"]
        lines += [f"| {where} | {written} |" for where, written in report.unknown] + [""]
    if report.title_differs:
        grouped: dict[tuple[str, str, str], list[str]] = {}
        for where, name, written, official in report.title_differs:
            grouped.setdefault((name, written, official), []).append(where)
        lines += ["## References kept, but the title differs from the official one", "",
                  "The reference exists, so it was converted. A different title is usually a paraphrase, but it can "
                  "mean a different clause was meant.", "",
                  "| Reference | Title in the workbook | Official title | Used in |", "|---|---|---|---|"]
        lines += [f"| {name} | {written} | {official} | {_where(places)} |"
                  for (name, written, official), places in sorted(grouped.items())] + [""]
    if report.paragraphs:
        grouped_p: dict[tuple[str, str], list[str]] = {}
        for where, name, written in report.paragraphs:
            grouped_p.setdefault((name, written), []).append(where)
        lines += ["## References to a paragraph of an article", "",
                  "The app links whole articles, so the paragraph detail is not kept.", "",
                  "| Article | Paragraph in the workbook | Used in |", "|---|---|---|"]
        lines += [f"| {name} | {written} | {_where(places)} |" for (name, written), places in sorted(grouped_p.items())] + [""]
    if report.headings:
        lines += ["## References to headings", "",
                  "These point at a heading that groups other clauses. They are kept, but framework coverage only "
                  "counts clauses that can be assessed, so pointing at the specific sub-clause is better.", ""]
        lines += [f"- {name}: {n} mapping{'s' if n > 1 else ''}" for name, n in sorted(report.headings.items())] + [""]
    return "\n".join(lines)


async def main() -> None:
    try:
        workbook, report, totals = await convert(sys.stdin.buffer.read())
    finally:
        await dispose_all()
    sys.stdout.buffer.write(workbook)
    sys.stderr.write(render(report, totals))


if __name__ == "__main__":
    asyncio.run(main())
