"""Evidence processing: extract text and summarise each file exactly once.

Later analysis (in the guided conversation) reuses `extracted_text` and `summary`
instead of re-reading the file."""

import io
import uuid

from pydantic import BaseModel, Field
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import tenant_of
from app.core.storage import get_object
from app.models import Evidence
from app.services import ai
from app.services.documents import IMAGES, PDF, to_content_blocks, to_text

MAX_TEXT = 60_000  # characters kept per file for analysis


class EvidenceDigest(BaseModel):
    summary: str = Field(description="Two to four sentences: what this document or image is and what it shows about the company's security practices (dates, owners, scope, approvals).")
    extracted_text: str | None = Field(description="For images or scanned documents only: a faithful transcription of the visible text and settings. Null when the text was already provided.")


SYSTEM = """You review evidence uploaded for a security and compliance assessment.
Describe what it is and what it demonstrates, factually. Note dates, version numbers, approvers, scope and any settings shown. Don't judge compliance."""


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
    data = get_object(ev.storage_key)

    text = ""
    if ev.content_type == PDF:
        text = pdf_text(data)
    elif ev.content_type not in IMAGES:
        text = to_text(data, ev.content_type)

    needs_model_read = ev.content_type in IMAGES or (ev.content_type == PDF and len(text.strip()) < 200)
    if needs_model_read:
        content = to_content_blocks(data, ev.content_type, ev.filename)
        content.append({"type": "text", "text": f"File: {ev.filename}. Summarise it and transcribe its visible text."})
    else:
        content = [{"type": "text", "text": f"File: {ev.filename}\n\n{text[:MAX_TEXT]}"},
                   {"type": "text", "text": "Summarise this file. The text is already extracted, so set extracted_text to null."}]

    digest = await ai.structured(output=EvidenceDigest, system=SYSTEM, content=content,
                                 model=ai.conversation_model(), effort="low", max_tokens=16000,
                                 usage=ai.UsageTag("evidence", tenant_of(db), ev.run_id))
    source = (digest.extracted_text or "") if needs_model_read else text
    ev.extracted_text = source[:MAX_TEXT] or None
    ev.summary = digest.summary
    ev.processing_status = "ready"
    await db.flush()
    return {"chars": len(ev.extracted_text or "")}
