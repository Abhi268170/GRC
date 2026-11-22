"""Evidence files of a run: upload and download."""

import asyncio
import hashlib
import uuid
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response as RawResponse
from sqlalchemy import select
from app.core.auth import TenantDB, TenantMember
from app.core.db import tenant_of
from app.core.queue import enqueue
from app.core.storage import get_object, put_object
from app.models import (
    Evidence,
    RunDomain,
)
from app.services import runs as svc
from app.core.uploads import clean_filename, content_disposition, read_limited
from app.services.documents import ALLOWED, IMAGES, PDF, guess_type, looks_like
from app.api.runs.schemas import EvidenceOut
from app.api.runs.views import _ai_paused

router = APIRouter(prefix="/runs", tags=["runs"])


MAX_EVIDENCE = 25 * 1024 * 1024

@router.post("/{run_id}/evidence", response_model=EvidenceOut, status_code=201)
async def upload_evidence(run_id: uuid.UUID, db: TenantDB, me: TenantMember, file: UploadFile = File(...)) -> EvidenceOut:
    run = await svc.get_run(db, me, run_id)
    svc.require_editable(run)
    domains = (await db.execute(select(RunDomain).where(RunDomain.run_id == run.id))).scalars().all()
    if not any(svc.can_work_on(me, run, rd) for rd in domains):
        raise HTTPException(403, "Every domain of this assessment is assigned to someone else")
    if await _ai_paused(db, run):
        raise HTTPException(409, "AI assistance for this assessment has reached its limit, so new evidence can't be read")
    filename = clean_filename(file.filename, "evidence")
    ctype = guess_type(filename, file.content_type)
    if ctype not in ALLOWED:
        raise HTTPException(422, "Upload a PDF, Word, Excel, CSV, text, PNG or JPG file")
    data = await read_limited(file, MAX_EVIDENCE, "Files can be up to 25 MB")
    if not looks_like(data, ctype):
        raise HTTPException(422, f"{filename} doesn't look like a {filename.rsplit('.', 1)[-1].upper()} file")
    digest = hashlib.sha256(data).hexdigest()
    ev = (await db.execute(select(Evidence).where(Evidence.run_id == run.id, Evidence.sha256 == digest))).scalar_one_or_none()
    if ev is None:  # the same file is stored and processed only once per run
        ev = Evidence(run_id=run.id, storage_key="", filename=filename,
                      content_type=ctype, size_bytes=len(data), sha256=digest, uploaded_by=me.id)
        db.add(ev)
        await db.flush()
        # The key never contains the file name: names are user input.
        ev.storage_key = f"tenants/{tenant_of(db)}/runs/{run.id}/evidence/{ev.id}"
        await asyncio.to_thread(put_object, ev.storage_key, data, ctype)
        await enqueue(db, type="process_evidence", ref_type="evidence", ref_id=ev.id)
    elif ev.processing_status == "failed":
        # Uploading the same file again is how a file that couldn't be read is retried.
        ev.processing_status, ev.processing_error = "pending", None
        await enqueue(db, type="process_evidence", ref_type="evidence", ref_id=ev.id)
    else:
        await db.commit()
    return EvidenceOut(id=ev.id, filename=ev.filename, content_type=ev.content_type, size_bytes=ev.size_bytes,
                       processing_status=ev.processing_status, summary=ev.summary, uploaded_by=ev.uploaded_by, created_at=ev.created_at)

@router.get("/{run_id}/evidence/{evidence_id}/file")
async def download_evidence(run_id: uuid.UUID, evidence_id: uuid.UUID, db: TenantDB, me: TenantMember) -> RawResponse:
    run = await svc.get_run(db, me, run_id)
    ev = await db.get(Evidence, evidence_id)
    if ev is None or ev.run_id != run.id:
        raise HTTPException(404, "File not found")
    data = await asyncio.to_thread(get_object, ev.storage_key)
    # Only PDFs and images open in the browser; everything else downloads. The type is never guessed.
    inline = ev.content_type == PDF or ev.content_type in IMAGES
    return RawResponse(data, media_type=ev.content_type, headers={
        "content-disposition": content_disposition(ev.filename, inline=inline), "x-content-type-options": "nosniff"})
