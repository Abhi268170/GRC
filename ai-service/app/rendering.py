"""How control library content is written into prompts. Shared by several tasks."""

from ai_contracts import Company, ControlContext, DomainScope, EvidenceFile, FileInput, Requirement

PDF = "application/pdf"
IMAGES = {"image/png", "image/jpeg"}

# In "brief" detail a control shows only what it is about (for question writing and intake).
BRIEF_TEXTS = ("Key requirement", "Why it matters", "Applies to", "Triggers")


def control(ctx: ControlContext, detail: str = "full") -> str:
    """detail="full": everything; "brief": what the control is about."""
    lines = [f"Control: {ctx.label}"]
    if ctx.area:
        lines.append(f"  Area: {ctx.area}")
    if ctx.responsible_role:
        lines.append(f"  Responsible role: {ctx.responsible_role}")
    for name, values in ctx.classification.items():
        if values and (detail == "full" or name == "Use case"):
            lines.append(f"  {name}: {', '.join(values)}")
    if ctx.risk_exposure_level and detail == "full":
        lines.append(f"  Company risk exposure: {ctx.risk_exposure_level}")
    for name, text in ctx.texts.items():
        if text and (detail == "full" or name in BRIEF_TEXTS):
            lines.append(f"  {name}: {text}")
    return "\n".join(lines)


def requirement_line(r: Requirement, evidence_label: str = "Evidence") -> str:
    """'- R1: statement [mandatory]' then the guidance (how to meet it) and evidence (what proves it)."""
    line = f"- {r.key}: {r.statement}"
    if r.mandatory is not None:
        line += " [mandatory]" if r.mandatory else " [optional]"
    if r.guidance:
        line += f"\n    How to meet it: {r.guidance}"
    if r.evidence:
        line += f"\n    {evidence_label}: {'; '.join(r.evidence)}"
    return line


def domain_requirements(domain: DomainScope, detail: str = "full", evidence_label: str = "Evidence") -> list[str]:
    """Requirements grouped under their control, with the control's context once per control."""
    lines: list[str] = []
    for c in domain.controls:
        lines.append("")
        lines.append(control(c.context, detail))
        lines += [requirement_line(r, evidence_label) for r in c.requirements]
    return lines


def company_profile(c: Company) -> str:
    """Three lines, as used at the top of prompts about one company."""
    return f"Company: {c.name}\nIndustry: {c.industry or 'unknown'}\nEmployees: {c.employees or 'unknown'}"


def company_context(c: Company) -> str:
    text = company_profile(c)
    if c.context_summary:
        text += f"\nContext from the pre-assessment intake: {c.context_summary}"
    return text


def evidence_block(ev: EvidenceFile, max_chars: int, empty_summary: str = "") -> str:
    """Evidence goes inside <evidence> tags; the prompts say to treat it as data, never as instructions."""
    return (f'<evidence id="{ev.id}" filename="{ev.filename}">\nSummary: {ev.summary or empty_summary}\n\n'
            f"{(ev.text or '')[:max_chars]}\n</evidence>")


def file_blocks(file: FileInput) -> list[dict]:
    """Content blocks that let the model read the file natively where possible."""
    if file.data_b64 and file.content_type == PDF:
        return [{"type": "document", "title": file.filename,
                 "source": {"type": "base64", "media_type": PDF, "data": file.data_b64}}]
    if file.data_b64 and file.content_type in IMAGES:
        return [{"type": "image", "source": {"type": "base64", "media_type": file.content_type, "data": file.data_b64}}]
    if file.text is None:
        raise ValueError(f"{file.filename}: send the extracted text for files of type {file.content_type}")
    return [{"type": "document", "title": file.filename,
             "source": {"type": "text", "media_type": "text/plain", "data": file.text}}]
