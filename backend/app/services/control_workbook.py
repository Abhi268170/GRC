"""The control library workbook: one .xlsx layout used for the empty template, the export and the import.

Pure openpyxl, no database. The import side (validation, diff, apply) lives in control_import.py."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

FORMAT = "trustup-controls/1"
MAX_BYTES = 10 * 1024 * 1024
MAX_CONTROLS = 1000
DROPDOWN_ROWS = 2000  # rows that get dropdowns in the template / export

MULTI_SEP = ";"


@dataclass(frozen=True)
class Col:
    key: str
    header: str
    width: int = 24
    required: bool = False  # the column must exist in the file (not: the cell must be filled)
    note: str = ""


CONTROL_COLS = [
    Col("code", "Control code", 14, True, "Blank for a new control. An existing code (e.g. IAM02) updates that control."),
    Col("key", "Import key", 12, True, "Only for new controls: any short text (e.g. N1) so requirements can point to it."),
    Col("base", "Base version", 14, True, "Filled in by export. Leave as is: it detects files older than the library."),
    Col("domain", "Domain", 10, True, "Domain abbreviation, e.g. IAM."),
    Col("title", "Title", 40, True),
    Col("area", "Area", 22, True),
    Col("company_risk_exposure", "Company risk exposure", 22, True),
    Col("responsible_role", "Responsible role", 26, True, "Organisational role name or abbreviation."),
    Col("control_types", "Control types", 26, True, "Several values allowed, separated by ;"),
    Col("protection_domains", "Protection domains", 26, True, "Several values allowed, separated by ;"),
    Col("security_capabilities", "Security capabilities", 26, True, "Several values allowed, separated by ;"),
    Col("protection_objectives", "Protection objectives", 26, True, "Several values allowed, separated by ;"),
    Col("use_cases", "Use cases", 26, True, "Several values allowed, separated by ;"),
    Col("short_description", "Short description", 40, True),
    Col("key_requirement", "Key requirement", 40, True),
    Col("risk_exposure", "Risk exposure", 40, True),
    Col("involved_parties", "Involved parties", 30, True),
    Col("triggers", "Triggers", 30, True),
    Col("supporting_documents", "Supporting documents", 30, True),
    Col("special_considerations", "Special considerations", 30, True),
    Col("subject_specific_support", "Subject-specific support", 30, True),
]

REQUIREMENT_COLS = [
    Col("control", "Control", 12, True, "The control's code, or its import key for a new control."),
    Col("code", "Requirement code", 16, True, "Blank for a new requirement. An existing code (e.g. IAM02-R03) keeps its history."),
    Col("key", "Import key", 12, True, "Only for new requirements that have templates: any short text (e.g. R1)."),
    Col("statement", "Statement", 50, True),
    Col("guidance", "Guidance", 50, True, "Short: how to meet the requirement."),
    Col("mandatory", "Mandatory", 11, True, "Yes, No or blank."),
    Col("evidence", "Evidence", 40, True, "One item per line (Alt+Enter for a new line in the cell)."),
    Col("clauses", "Framework clauses", 30, True, "FRAMEWORK:ref separated by ;  e.g. ISO27001:A.5.15; SOC2:CC6.1"),
]

TEMPLATE_COLS = [
    Col("requirement", "Requirement", 16, True, "The requirement's code, or its import key for a new requirement."),
    Col("kind", "Kind", 10, True, "Action or Risk."),
    Col("title", "Title", 40, True),
    Col("description", "Description", 60, True),
]

SHEETS = {"Controls": CONTROL_COLS, "Requirements": REQUIREMENT_COLS, "Templates": TEMPLATE_COLS}

INSTRUCTIONS = [
    ("How this file works", True),
    ("Export the library, edit it here, and import it again. The import shows a preview of every change before "
     "anything is written, and creates drafts that you publish separately.", False),
    ("", False),
    ("Sheets", True),
    ("Controls: one row per control.", False),
    ("Requirements: one row per requirement. The order of rows within a control is the requirement order (1 to 10 "
     "per control).", False),
    ("Templates: one row per action item or risk template. Title and description are both required.", False),
    ("Lists: the values you can use. Single-value columns have dropdowns; for several values, separate them with ;", False),
    ("", False),
    ("Rules", True),
    ("New control: leave Control code blank and give it an Import key (e.g. N1). Its code is assigned on import.", False),
    ("New requirement: leave Requirement code blank. Give it an Import key only if a template needs to point to it.", False),
    ("Codes are assigned by the app: don't type a new code, and don't change the Base version column.", False),
    ("Controls not in the file are left as they are. Nothing is ever deleted by an import.", False),
    ("Leaving out an existing requirement removes it from the control's next version; the preview asks you to "
     "confirm each removal.", False),
    ("Values must already exist (domains, master data, roles, framework clauses). Add missing ones in the app "
     "first, then import again.", False),
    ("A control's domain can't change once it has been published.", False),
    ("If any row has an error, nothing is imported. Download the file with errors marked, fix it, and import again.", False),
]

HEADER_FILL = PatternFill("solid", fgColor="E8EFE6")
ERROR_FILL = PatternFill("solid", fgColor="F8C9C4")
WARN_FILL = PatternFill("solid", fgColor="FCE9B8")


@dataclass
class Lists:
    """Values offered in the Lists sheet and the dropdowns."""
    domains: list[tuple[str, str]]                 # (abbreviation, name)
    master: dict[str, list[tuple[str, str]]]       # column key -> [(label, code)]
    roles: list[tuple[str, str]]                   # (name, abbreviation)
    clauses: list[tuple[str, str]]                 # ("ISO27001:A.5.15", title)


# ---------- writing ----------


def _header(ws, cols: list[Col]) -> None:
    for i, c in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=i, value=c.header)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center")
        if c.note:
            cell.comment = Comment(c.note, "TrustUp", width=260, height=90)
        ws.column_dimensions[get_column_letter(i)].width = c.width
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 22


def _write_rows(ws, cols: list[Col], rows: list[dict]) -> None:
    wrap = Alignment(wrap_text=True, vertical="top")
    for r, row in enumerate(rows, start=2):
        for i, c in enumerate(cols, start=1):
            value = row.get(c.key)
            cell = ws.cell(row=r, column=i, value=value if value not in ("", None) else None)
            cell.alignment = wrap


def _lists_sheet(wb: Workbook, lists: Lists) -> dict[str, str]:
    """Writes the Lists sheet; returns column key -> range formula for its dropdowns."""
    ws = wb.create_sheet("Lists")
    columns: list[tuple[str, str, list[str]]] = [
        ("domain", "Domains", [a for a, _ in lists.domains]),
        ("domain_name", "Domain name", [n for _, n in lists.domains]),
        ("area", "Area", [label for label, _ in lists.master.get("area", [])]),
        ("company_risk_exposure", "Company risk exposure",
         [label for label, _ in lists.master.get("company_risk_exposure", [])]),
        ("responsible_role", "Responsible role", [n for n, _ in lists.roles]),
        ("role_abbreviation", "Role abbreviation", [a for _, a in lists.roles]),
        *[(k, h, [label for label, _ in lists.master.get(k, [])]) for k, h in (
            ("control_types", "Control types"), ("protection_domains", "Protection domains"),
            ("security_capabilities", "Security capabilities"), ("protection_objectives", "Protection objectives"),
            ("use_cases", "Use cases"))],
        ("mandatory", "Mandatory", ["Yes", "No"]),
        ("kind", "Kind", ["Action", "Risk"]),
        ("clauses", "Framework clauses", [c for c, _ in lists.clauses]),
        ("clause_title", "Clause title", [t for _, t in lists.clauses]),
    ]
    ranges = {}
    for i, (key, header, values) in enumerate(columns, start=1):
        letter = get_column_letter(i)
        cell = ws.cell(row=1, column=i, value=header)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        for r, value in enumerate(values, start=2):
            ws.cell(row=r, column=i, value=value)
        ws.column_dimensions[letter].width = 40 if key in ("clause_title", "domain_name") else 26
        ranges[key] = f"=Lists!${letter}$2:${letter}${max(2, len(values) + 1)}"
    ws.freeze_panes = "A2"
    ws.protection.sheet = True  # reference only
    return ranges


def _dropdown(ws, cols: list[Col], key: str, formula: str) -> None:
    idx = next(i for i, c in enumerate(cols, start=1) if c.key == key)
    letter = get_column_letter(idx)
    # Warning style: the dropdown helps, but codes and abbreviations typed by hand are accepted too.
    dv = DataValidation(type="list", formula1=formula, allow_blank=True, errorStyle="warning",
                        error="Not in the list. Check the Lists sheet.", errorTitle="Unknown value")
    dv.add(f"{letter}2:{letter}{DROPDOWN_ROWS}")
    ws.add_data_validation(dv)


def build_workbook(lists: Lists, controls: list[dict], requirements: list[dict], templates: list[dict],
                   exported_by: str | None = None) -> bytes:
    wb = Workbook()
    ins = wb.active
    ins.title = "Instructions"
    ins.column_dimensions["A"].width = 120
    for r, (line, bold) in enumerate(INSTRUCTIONS, start=1):
        cell = ins.cell(row=r, column=1, value=line)
        cell.alignment = Alignment(wrap_text=True)
        if bold:
            cell.font = Font(bold=True, size=12)

    sheets = {}
    for name, cols in SHEETS.items():
        ws = wb.create_sheet(name)
        _header(ws, cols)
        sheets[name] = ws
    _write_rows(sheets["Controls"], CONTROL_COLS, controls)
    _write_rows(sheets["Requirements"], REQUIREMENT_COLS, requirements)
    _write_rows(sheets["Templates"], TEMPLATE_COLS, templates)

    ranges = _lists_sheet(wb, lists)
    for key in ("domain", "area", "company_risk_exposure", "responsible_role"):
        _dropdown(sheets["Controls"], CONTROL_COLS, key, ranges[key])
    _dropdown(sheets["Requirements"], REQUIREMENT_COLS, "mandatory", ranges["mandatory"])
    _dropdown(sheets["Templates"], TEMPLATE_COLS, "kind", ranges["kind"])

    meta = wb.create_sheet("_meta")
    for r, (k, value) in enumerate((("format", FORMAT), ("exported_at", datetime.now(UTC).isoformat(timespec="seconds")),
                                    ("exported_by", exported_by or "")), start=1):
        meta.cell(row=r, column=1, value=k)
        meta.cell(row=r, column=2, value=value)
    meta.sheet_state = "hidden"

    wb.active = 1  # open on Controls
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------- reading ----------


@dataclass
class Row:
    sheet: str
    row: int  # Excel row number
    values: dict[str, str]


@dataclass
class Parsed:
    controls: list[Row] = field(default_factory=list)
    requirements: list[Row] = field(default_factory=list)
    templates: list[Row] = field(default_factory=list)
    error: str | None = None  # the file itself is unusable; nothing else is checked


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_workbook(data: bytes) -> Parsed:
    if len(data) > MAX_BYTES:
        return Parsed(error="The file is larger than 10 MB.")
    try:
        wb = load_workbook(BytesIO(data), data_only=True)
    except Exception:  # noqa: BLE001 - any unreadable file gets the same message
        return Parsed(error="This isn't a readable .xlsx file. Download the template and fill that in.")

    if "_meta" not in wb.sheetnames or _text(wb["_meta"].cell(row=1, column=2).value) != FORMAT:
        return Parsed(error="This isn't a TrustUp control workbook (or it's from an unsupported version). "
                            "Download the template or export the library, and fill that in.")
    out = Parsed()
    for name, cols in SHEETS.items():
        if name not in wb.sheetnames:
            return Parsed(error=f"The {name} sheet is missing.")
        ws = wb[name]
        headers = {_text(c.value).lower(): i for i, c in enumerate(ws[1]) if _text(c.value)}
        missing = [c.header for c in cols if c.required and c.header.lower() not in headers]
        if missing:
            return Parsed(error=f"The {name} sheet is missing the column{'s' if len(missing) > 1 else ''}: "
                                + ", ".join(missing) + ".")
        index = {c.key: headers[c.header.lower()] for c in cols if c.header.lower() in headers}
        rows: list[Row] = []
        for r, cells in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            values = {k: _text(cells[i]) if i < len(cells) else "" for k, i in index.items()}
            if any(values.values()):
                rows.append(Row(name, r, values))
        setattr(out, name.lower(), rows)
    if len(out.controls) > MAX_CONTROLS:
        return Parsed(error=f"The file has {len(out.controls)} controls; the limit is {MAX_CONTROLS} per import.")
    if not out.controls:
        return Parsed(error="The Controls sheet has no rows.")
    return out


def split_multi(value: str) -> list[str]:
    return [x.strip() for x in value.replace("\n", MULTI_SEP).split(MULTI_SEP) if x.strip()]


def split_lines(value: str) -> list[str]:
    return [x.strip() for x in value.splitlines() if x.strip()]


# ---------- marking errors ----------


def mark_issues(data: bytes, issues: list[dict]) -> bytes:
    """The uploaded workbook with every problem cell highlighted and explained, plus an Import issues sheet."""
    wb = load_workbook(BytesIO(data))
    for issue in issues:
        sheet = issue.get("sheet")
        if sheet not in SHEETS or sheet not in wb.sheetnames or not issue.get("row"):
            continue
        ws = wb[sheet]
        headers = {_text(c.value).lower(): i + 1 for i, c in enumerate(ws[1]) if _text(c.value)}
        col = headers.get((issue.get("column") or "").lower(), 1)
        cell = ws.cell(row=issue["row"], column=col)
        cell.fill = ERROR_FILL if issue["level"] == "error" else WARN_FILL
        text = issue["message"] + (f"\nDid you mean: {issue['suggestion']}?" if issue.get("suggestion") else "")
        if cell.comment:
            text = cell.comment.text + "\n\n" + text
        cell.comment = Comment(text, "TrustUp import", width=300, height=120)

    if "Import issues" in wb.sheetnames:
        del wb["Import issues"]
    ws = wb.create_sheet("Import issues", 0)
    cols = [("Level", 10), ("Sheet", 14), ("Row", 7), ("Column", 22), ("Value", 30), ("Problem", 70), ("Did you mean", 30)]
    for i, (h, w) in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=i, value=h)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        ws.column_dimensions[get_column_letter(i)].width = w
    for r, issue in enumerate(issues, start=2):
        for i, value in enumerate((issue["level"].capitalize(), issue.get("sheet"), issue.get("row"), issue.get("column"),
                                   issue.get("value"), issue["message"], issue.get("suggestion")), start=1):
            cell = ws.cell(row=r, column=i, value=value)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if i == 1:
                cell.fill = ERROR_FILL if issue["level"] == "error" else WARN_FILL
    ws.freeze_panes = "A2"
    wb.active = 0
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
