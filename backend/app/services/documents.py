"""Read uploaded files: extract their text, and prepare them for the AI service."""

import base64
import csv
import io
import zipfile

from ai_contracts import FileInput
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


class FileTooLarge(ValueError):
    """The file expands to more than we are willing to read."""


# Office files are zip archives: a small upload can expand to gigabytes. Checked before parsing.
MAX_UNZIPPED_BYTES = 200 * 1024 * 1024
MAX_ZIP_MEMBERS = 5000
MAX_PDF_PAGES = 600
MAX_XLSX_COLUMNS = 200
MAX_XLSX_SHEETS = 50

_SIGNATURES = {
    PDF: (b"%PDF-",), DOCX: (b"PK\x03\x04",), XLSX: (b"PK\x03\x04",),
    "image/png": (b"\x89PNG\r\n\x1a\n",), "image/jpeg": (b"\xff\xd8\xff",),
}


def looks_like(data: bytes, content_type: str) -> bool:
    """The file starts the way its type says it should. Text types only need to be free of NUL bytes."""
    signatures = _SIGNATURES.get(content_type)
    if signatures is None:
        return b"\x00" not in data[:8192]
    return data.startswith(signatures)


def check_archive(data: bytes) -> None:
    """Refuse zip-based files (docx, xlsx) that would expand beyond the limits."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
    except zipfile.BadZipFile as e:
        raise FileTooLarge("The file is damaged or not a valid document") from e
    if len(members) > MAX_ZIP_MEMBERS or sum(m.file_size for m in members) > MAX_UNZIPPED_BYTES:
        raise FileTooLarge("The file is too large to read once it is unpacked")


def docx_text(data: bytes) -> str:
    check_archive(data)
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def xlsx_text(data: bytes, max_rows: int = 2000) -> str:
    check_archive(data)
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets[:MAX_XLSX_SHEETS]:
        out.append(f"## Sheet: {ws.title}")
        for i, row in enumerate(ws.iter_rows(values_only=True, max_col=MAX_XLSX_COLUMNS)):
            if i >= max_rows:
                out.append("… (truncated)")
                break
            out.append(" | ".join("" if v is None else str(v) for v in row))
    return "\n".join(out)


def file_input(data: bytes, content_type: str, filename: str, text: str | None = None) -> FileInput:
    """What the AI service gets for a file: PDFs and images as they are (the model reads them
    natively), everything else as extracted text. Pass `text` when it is already extracted."""
    if text is not None:
        return FileInput(filename=filename, content_type=content_type, text=text)
    if content_type == PDF or content_type in IMAGES:
        return FileInput(filename=filename, content_type=content_type, data_b64=base64.b64encode(data).decode())
    return FileInput(filename=filename, content_type=content_type, text=to_text(data, content_type))


def to_text(data: bytes, content_type: str) -> str:
    if content_type == DOCX:
        return docx_text(data)
    if content_type == XLSX:
        return xlsx_text(data)
    if content_type == "text/csv":
        rows = csv.reader(io.StringIO(data.decode("utf-8", errors="replace")))
        return "\n".join(" | ".join(r) for r in rows)
    return data.decode("utf-8", errors="replace")
