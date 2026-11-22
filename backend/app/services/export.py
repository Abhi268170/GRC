"""Render an assessment report to PDF (reportlab) and DOCX (python-docx)."""

import io
from datetime import datetime
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INDIGO = colors.HexColor("#4338CA")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#E5E7EB")
MATURITY = {0: "Non-existent", 1: "Initial", 2: "Defined", 3: "Managed", 4: "Optimized"}


def _score(v) -> str:
    return "—" if v is None else f"{v:.1f} / 4"


def _rating(r: dict) -> str:
    return "N/A" if r["na"] else ("—" if r["rating"] is None else f"{r['rating']} {MATURITY[r['rating']]}")


def _date(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d %B %Y")


def to_pdf(content: dict, actions: list[dict], risks: list[dict]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                            title=content["title"], author=content["company"]["name"])
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=22, leading=26, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=14, textColor=INDIGO, spaceBefore=14, spaceAfter=6, keepWithNext=1)
    h3 = ParagraphStyle("h3", parent=ss["Heading3"], fontSize=11, spaceBefore=8, spaceAfter=3, keepWithNext=1)
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=9.5, leading=13.5, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11.5, textColor=MUTED)
    cell = ParagraphStyle("cell", parent=body, fontSize=8.5, leading=11)

    def p(text, style=body):
        return Paragraph(escape(text or ""), style)

    def table(rows, widths, header=True):
        t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, LINE),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6") if header else colors.white),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        return t

    c = content
    story = [
        p(c["company"]["name"], small),
        Paragraph(escape(c["title"]), h1),
        p(f"Assessment report · version {c['version']} · generated {_date(c['generated_at'])}", small),
        Spacer(1, 10),
        table([[p("Overall maturity", cell), p(_score(c["overall"]["score"]), cell)],
               *[[p(f["name"] + " coverage", cell), p("—" if f["pct"] is None else f"{f['pct']}% ({f['covered']}/{f['considered']} clauses)", cell)] for f in c["frameworks"]]],
              [70 * mm, 104 * mm], header=False),
        Paragraph("Executive summary", h2), p(c["executive_summary"]), Spacer(1, 4), p(c["overall"].get("explanation"), small),
        Paragraph("Results by domain", h2),
        table([[p("Domain", cell), p("Score", cell), p("Summary", cell)]] +
              [[p(d["name"], cell), p(_score(d["score"]), cell), p(d.get("summary", ""), cell)] for d in c["domains"]],
              [45 * mm, 22 * mm, 107 * mm]),
    ]
    if actions:
        story += [Paragraph("Action items", h2),
                  table([[p("Priority", cell), p("Action", cell), p("Status", cell)]] +
                        [[p(a["priority"].title(), cell), Paragraph(f"<b>{escape(a['title'])}</b><br/>{escape(a['description'] or '')}", cell), p(a["status"].replace("_", " ").title(), cell)] for a in actions],
                        [22 * mm, 128 * mm, 24 * mm])]
    if risks:
        story += [Paragraph("Risks", h2),
                  table([[p("Score", cell), p("Risk", cell), p("L × I", cell)]] +
                        [[p(str(r["likelihood"] * r["impact"]), cell), Paragraph(f"<b>{escape(r['title'])}</b><br/>{escape(r['description'] or '')}", cell), p(f"{r['likelihood']} × {r['impact']}", cell)] for r in risks],
                        [16 * mm, 136 * mm, 22 * mm])]
    story.append(PageBreak())
    story.append(Paragraph("Detailed findings", h2))
    for d in c["domains"]:
        story.append(Paragraph(f"{escape(d['name'])} · {_score(d['score'])}", h3))
        if d.get("strengths"):
            story.append(p("Strengths: " + "; ".join(d["strengths"]), small))
        if d.get("gaps"):
            story.append(p("Gaps: " + "; ".join(d["gaps"]), small))
        story.append(Spacer(1, 4))
        story.append(table([[p("Req.", cell), p("Requirement and rationale", cell), p("Rating", cell)]] +
                           [[p(r["key"], cell), Paragraph(f"{escape(r['statement'])}<br/><font color='#6B7280'>{escape(r['rationale'] or '')}</font>", cell), p(_rating(r), cell)] for r in d["requirements"]],
                           [14 * mm, 136 * mm, 24 * mm]))

    def footer(canvas, _doc):
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"{c['company']['name']} · {c['title']}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {_doc.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def to_docx(content: dict, actions: list[dict], risks: list[dict]) -> bytes:
    c = content
    doc = Document()
    styles = doc.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(10)

    def muted(par):
        for run in par.runs:
            run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
            run.font.size = Pt(9)
        return par

    muted(doc.add_paragraph(c["company"]["name"]))
    doc.add_heading(c["title"], level=0)
    muted(doc.add_paragraph(f"Assessment report · version {c['version']} · generated {_date(c['generated_at'])}"))

    t = doc.add_table(rows=0, cols=2)
    t.style = "Light Grid Accent 1"
    for label, value in [("Overall maturity", _score(c["overall"]["score"]))] + [
            (f["name"] + " coverage", "—" if f["pct"] is None else f"{f['pct']}% ({f['covered']}/{f['considered']} clauses)") for f in c["frameworks"]]:
        row = t.add_row().cells
        row[0].text, row[1].text = label, value

    doc.add_heading("Executive summary", level=1)
    doc.add_paragraph(c["executive_summary"])
    muted(doc.add_paragraph(c["overall"].get("explanation") or ""))

    doc.add_heading("Results by domain", level=1)
    t = doc.add_table(rows=1, cols=3)
    t.style = "Light Grid Accent 1"
    t.rows[0].cells[0].text, t.rows[0].cells[1].text, t.rows[0].cells[2].text = "Domain", "Score", "Summary"
    for d in c["domains"]:
        row = t.add_row().cells
        row[0].text, row[1].text, row[2].text = d["name"], _score(d["score"]), d.get("summary", "")

    if actions:
        doc.add_heading("Action items", level=1)
        for a in actions:
            par = doc.add_paragraph(style="List Bullet")
            par.add_run(f"[{a['priority'].title()}] {a['title']}").bold = True
            if a["description"]:
                par.add_run(f" — {a['description']}")
    if risks:
        doc.add_heading("Risks", level=1)
        for r in risks:
            par = doc.add_paragraph(style="List Bullet")
            par.add_run(f"{r['title']} (likelihood {r['likelihood']} × impact {r['impact']} = {r['likelihood'] * r['impact']})").bold = True
            if r["description"]:
                par.add_run(f" — {r['description']}")

    doc.add_page_break()
    doc.add_heading("Detailed findings", level=1)
    for d in c["domains"]:
        doc.add_heading(f"{d['name']} · {_score(d['score'])}", level=2)
        if d.get("strengths"):
            muted(doc.add_paragraph("Strengths: " + "; ".join(d["strengths"])))
        if d.get("gaps"):
            muted(doc.add_paragraph("Gaps: " + "; ".join(d["gaps"])))
        t = doc.add_table(rows=1, cols=3)
        t.style = "Light Grid Accent 1"
        t.rows[0].cells[0].text, t.rows[0].cells[1].text, t.rows[0].cells[2].text = "Req.", "Requirement and rationale", "Rating"
        for r in d["requirements"]:
            row = t.add_row().cells
            row[0].text = r["key"]
            row[1].text = r["statement"]
            if r["rationale"]:
                muted(row[1].add_paragraph(r["rationale"]))
            row[2].text = _rating(r)
            row[2].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
