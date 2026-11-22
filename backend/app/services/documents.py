"""Turn an uploaded file into Claude content blocks (or plain text)."""

import base64
import csv
import io

from docx import Document
from openpyxl import load_workbook

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
IMAGES = {"image/png", "image/jpeg"}
TEXT = {"text/plain", "text/markdown", "text/csv"}

ALLOWED = {PDF, DOCX, XLSX, *IMAGES, *TEXT}


def guess_type(filename: str, declared: str | None) -> str:
    name = filename.lower()
    by_ext = {
        ".pdf": PDF, ".docx": DOCX, ".xlsx": XLSX, ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
    }
    for ext, ctype in by_ext.items():
        if name.endswith(ext):
            return ctype
    return declared or "application/octet-stream"


def docx_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def xlsx_text(data: bytes, max_rows: int = 2000) -> str:
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"## Sheet: {ws.title}")
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows:
                out.append("… (truncated)")
                break
            out.append(" | ".join("" if v is None else str(v) for v in row))
    return "\n".join(out)


def to_content_blocks(data: bytes, content_type: str, filename: str) -> list[dict]:
    """Content blocks that let Claude read the file natively where possible."""
    if content_type == PDF:
        return [{
            "type": "document",
            "source": {"type": "base64", "media_type": PDF, "data": base64.b64encode(data).decode()},
            "title": filename,
        }]
    if content_type in IMAGES:
        return [{
            "type": "image",
            "source": {"type": "base64", "media_type": content_type, "data": base64.b64encode(data).decode()},
        }]
    return [{
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": to_text(data, content_type)},
        "title": filename,
    }]


def to_text(data: bytes, content_type: str) -> str:
    if content_type == DOCX:
        return docx_text(data)
    if content_type == XLSX:
        return xlsx_text(data)
    if content_type == "text/csv":
        rows = csv.reader(io.StringIO(data.decode("utf-8", errors="replace")))
        return "\n".join(" | ".join(r) for r in rows)
    return data.decode("utf-8", errors="replace")
