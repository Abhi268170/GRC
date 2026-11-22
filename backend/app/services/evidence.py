"""Evidence processing: extract text and summarise each file exactly once.

Later analysis (in the guided conversation) reuses `extracted_text` and `summary`
instead of re-reading the file."""

import asyncio
import io
import uuid

import ai_contracts as contracts
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import tenant_of
from app.core.storage import get_object
from app.models import Evidence
from app.services import ai
from app.services.documents import IMAGES, PDF, file_input, to_text

MAX_TEXT = 60_000  # characters kept per file for analysis


def pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:  # noqa: BLE001 - unreadable PDFs fall back to the model reading the file
        return ""


async def process(db: AsyncSession, evidence_id: uuid.UUID) -> dict:
    ev = await db.get(Evidence, evidence_id)
    if ev.processing_status == "ready":
        return {"skipped": "already processed"}
    if await ai.run_spend(db, ev.run_id) >= get_settings().run_ai_budget_usd:
        raise ai.AIError("AI assistance for this assessment has reached its limit")
    data = await asyncio.to_thread(get_object, ev.storage_key)

    text = ""
    if ev.content_type == PDF:
        text = await asyncio.to_thread(pdf_text, data)
    elif ev.content_type not in IMAGES:
        text = await asyncio.to_thread(to_text, data, ev.content_type)

    # Images and scanned PDFs have no text to extract: the model reads the file and transcribes it.
    needs_model_read = ev.content_type in IMAGES or (ev.content_type == PDF and len(text.strip()) < 200)
    file = file_input(data, ev.content_type, ev.filename, text=None if needs_model_read else text[:MAX_TEXT])
    digest = await ai.call("/evidence/digest", contracts.EvidenceDigestIn(file=file), contracts.EvidenceDigest,
                           ai.UsageTag("evidence", tenant_of(db), ev.run_id))
    source = (digest.extracted_text or "") if needs_model_read else text
    ev.extracted_text = source[:MAX_TEXT] or None
    ev.summary = digest.summary
    ev.processing_status = "ready"
    await db.flush()
    return {"chars": len(ev.extracted_text or "")}
