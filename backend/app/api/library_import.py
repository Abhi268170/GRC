"""Control library Excel export and import (Super Admin). See CONTROL_IMPORT_PLAN.md."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel
from sqlalchemy import select, update

from app.api.library import _control_version_out, get_control
from app.core.auth import ControlDB, SuperAdmin
from app.core.storage import delete_object, get_object, put_object
from app.models import AppUser, Control, ControlImport, ControlVersion, Domain, DomainVersion, Requirement
from app.services import control_import as ci
from app.services import versioning as v
from app.services.control_workbook import MAX_BYTES, build_workbook, mark_issues

router = APIRouter(prefix="/library", tags=["library-import"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PREVIEW_TTL = timedelta(hours=24)


class ImportDraft(BaseModel):
    control_id: uuid.UUID
    code: str
    version_code: str
    title: str
    status: str  # draft / published / deprecated


class ImportOut(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    created_at: datetime
    created_by: str
    applied_at: datetime | None
    summary: dict
    report: dict
    choices: dict
    blockers: list[str]
    drafts: list[ImportDraft]


class ImportListItem(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    created_at: datetime
    created_by: str
    applied_at: datetime | None
    summary: dict


class Choices(BaseModel):
    conflicts: dict[str, str] = {}  # control code -> overwrite | skip
    removals: list[str] = []        # requirement codes whose removal is confirmed


class PublishResult(BaseModel):
    published: list[str]
    not_published: list[dict]  # {"code", "reasons"}


def _download(data: bytes, name: str) -> RawResponse:
    return RawResponse(data, media_type=XLSX, headers={"content-disposition": f'attachment; filename="{name}"'})


def _expired(imp: ControlImport) -> bool:
    return imp.status == "preview" and datetime.now(UTC) - imp.created_at > PREVIEW_TTL


async def _get(db: ControlDB, import_id: uuid.UUID) -> ControlImport:
    imp = await db.get(ControlImport, import_id)
    if imp is None:
        raise HTTPException(404, "Import not found")
    if _expired(imp):
        imp.status = "expired"
        await db.commit()
    return imp


async def _out(db: ControlDB, imp: ControlImport) -> ImportOut:
    user = await db.get(AppUser, imp.created_by)
    rows = (await db.execute(
        select(ControlVersion, Control.code).join(Control, Control.id == ControlVersion.control_id)
        .where(ControlVersion.import_id == imp.id).order_by(Control.code)
    )).all()
    report = imp.report or {}
    return ImportOut(
        id=imp.id, filename=imp.filename, status=imp.status, created_at=imp.created_at,
        created_by=user.full_name if user else "", applied_at=imp.applied_at, summary=imp.summary, report=report,
        choices=imp.choices,
        blockers=ci.blockers(report.get("controls", []), report.get("issues", []), imp.choices)
        if imp.status == "preview" else [],
        drafts=[ImportDraft(control_id=cv.control_id, code=code, version_code=f"{code}.{cv.version:04d}", title=cv.title,
                            status=cv.status)
                for cv, code in rows],
    )


# ---------- template and export ----------


@router.get("/import-template")
async def download_template(db: ControlDB, user: SuperAdmin) -> RawResponse:
    lists = await ci.workbook_lists(db)
    return _download(build_workbook(lists, [], [], [], user.full_name), "trustup-controls-template.xlsx")


@router.get("/export")
async def export_library(db: ControlDB, user: SuperAdmin, domain_id: uuid.UUID | None = None,
                         include_drafts: bool = False) -> RawResponse:
    lists = await ci.workbook_lists(db)
    domains = {d.id: d.abbreviation for d in (await db.execute(select(Domain))).scalars().all()}
    outs = []
    for control in (await db.execute(select(Control).order_by(Control.code))).scalars().all():
        detail = await get_control(control.id, db, user)
        version = (detail.draft or detail.published) if include_drafts else detail.published
        if version is None or (domain_id and version.domain_id != domain_id):
            continue
        outs.append((control.code, version))
    controls, requirements, templates = ci.export_rows(outs, domains)
    suffix = f"-{domains[domain_id].lower()}" if domain_id in domains else ""
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return _download(build_workbook(lists, controls, requirements, templates, user.full_name),
                     f"trustup-controls{suffix}-{stamp}.xlsx")


# ---------- import ----------


@router.post("/imports", response_model=ImportOut, status_code=201)
async def preview_import(db: ControlDB, user: SuperAdmin, file: UploadFile = File(...)) -> ImportOut:
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "The file is larger than 10 MB")
    result = await ci.preview(db, data)
    digest = hashlib.sha256(data).hexdigest()
    earlier = (await db.execute(select(ControlImport).where(ControlImport.status == "applied")
                                .where(ControlImport.summary["sha256"].astext == digest)
                                .order_by(ControlImport.applied_at.desc()))).scalars().first()
    if earlier:
        result.issues.insert(0, {
            "level": "warning", "sheet": None, "row": None, "column": None, "value": None, "control": None,
            "suggestion": None,
            "message": f"This exact file was already imported on {earlier.applied_at:%d %b %Y %H:%M}. Rows without a "
                       "code in it would be created again: export the library for a fresh copy instead.",
        })
    # Only the newest preview can be applied.
    await db.execute(update(ControlImport).where(ControlImport.status == "preview").values(status="expired"))
    imp = ControlImport(filename=file.filename or "controls.xlsx", file_key="", created_by=user.id,
                        summary={**result.summary(), "sha256": digest}, report=result.report(), choices={},
                        fingerprints=result.fingerprints)
    db.add(imp)
    await db.flush()
    imp.file_key = f"control-imports/{imp.id}.xlsx"
    put_object(imp.file_key, data, XLSX)
    await db.commit()
    await db.refresh(imp)
    return await _out(db, imp)


@router.get("/imports", response_model=list[ImportListItem])
async def list_imports(db: ControlDB, _: SuperAdmin) -> list[ImportListItem]:
    rows = (await db.execute(
        select(ControlImport, AppUser.full_name).join(AppUser, AppUser.id == ControlImport.created_by)
        .order_by(ControlImport.created_at.desc()).limit(50)
    )).all()
    return [ImportListItem(id=i.id, filename=i.filename, status="expired" if _expired(i) else i.status,
                           created_at=i.created_at, created_by=name, applied_at=i.applied_at, summary=i.summary)
            for i, name in rows]


@router.get("/imports/{import_id}", response_model=ImportOut)
async def get_import(import_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> ImportOut:
    return await _out(db, await _get(db, import_id))


@router.put("/imports/{import_id}/choices", response_model=ImportOut)
async def set_choices(import_id: uuid.UUID, body: Choices, db: ControlDB, _: SuperAdmin) -> ImportOut:
    imp = await _get(db, import_id)
    if imp.status != "preview":
        raise HTTPException(409, "This import is no longer open. Upload the file again.")
    if any(c not in ("overwrite", "skip") for c in body.conflicts.values()):
        raise HTTPException(422, "A conflict choice is overwrite or skip")
    imp.choices = body.model_dump()
    await db.commit()
    return await _out(db, imp)


@router.get("/imports/{import_id}/issues.xlsx")
async def download_issues(import_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> RawResponse:
    imp = await _get(db, import_id)
    issues = (imp.report or {}).get("issues", [])
    data = get_object(imp.file_key)
    try:
        marked = mark_issues(data, issues)
    except Exception:  # noqa: BLE001 - the upload wasn't a readable workbook: nothing to mark
        raise HTTPException(409, "The file couldn't be opened, so there's nothing to mark.") from None
    stem = imp.filename.rsplit(".", 1)[0]
    return _download(marked, f"{stem}-issues.xlsx")


@router.post("/imports/{import_id}/apply", response_model=ImportOut)
async def apply_import(import_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> ImportOut:
    imp = await _get(db, import_id)
    if imp.status != "preview":
        raise HTTPException(409, "This import is no longer open. Upload the file again.")
    try:
        done = await ci.apply(db, get_object(imp.file_key), imp.id, imp.fingerprints, imp.choices)
    except HTTPException:
        await db.rollback()
        raise
    imp.status, imp.applied_at = "applied", datetime.now(UTC)
    imp.summary = {**imp.summary, "created": len(done["created"]), "updated": len(done["updated"])}
    await db.commit()
    return await _out(db, imp)


@router.post("/imports/{import_id}/publish", response_model=PublishResult)
async def publish_imported(import_id: uuid.UUID, db: ControlDB, user: SuperAdmin) -> PublishResult:
    """Publish every draft this import created that is ready; report the rest and why."""
    await _get(db, import_id)
    rows = (await db.execute(
        select(ControlVersion, Control.code).join(Control, Control.id == ControlVersion.control_id)
        .where(ControlVersion.import_id == import_id, ControlVersion.status == "draft").order_by(Control.code)
    )).all()
    published, skipped = [], []
    for cv, code in rows:
        reasons = []
        if not await v.get_version(db, DomainVersion, "domain_id", cv.domain_id, "published"):
            reasons.append("its domain isn't published")
        out = await _control_version_out(db, cv, code)
        if out.missing_for_publish:
            reasons.append("missing " + ", ".join(out.missing_for_publish))
        if reasons:
            skipped.append({"code": code, "reasons": reasons})
            continue
        await v.publish(db, ControlVersion, "control_id", cv.control_id, user.id)
        published.append(code)
    await db.commit()
    return PublishResult(published=published, not_published=skipped)


@router.delete("/imports/{import_id}/drafts", status_code=204)
async def discard_imported_drafts(import_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> None:
    """Discard the drafts this import created that haven't been published (controls that only existed as one of
    those drafts are removed entirely, as when discarding in the editor)."""
    await _get(db, import_id)
    drafts = (await db.execute(select(ControlVersion).where(ControlVersion.import_id == import_id,
                                                            ControlVersion.status == "draft"))).scalars().all()
    for cv in drafts:
        has_published = await v.get_version(db, ControlVersion, "control_id", cv.control_id, "published")
        control_id = cv.control_id
        await db.delete(cv)
        if not has_published:
            await db.flush()
            for req in (await db.execute(select(Requirement).where(Requirement.control_id == control_id))).scalars():
                await db.delete(req)
            await db.delete(await db.get(Control, control_id))
    await db.commit()


@router.delete("/imports/{import_id}", status_code=204)
async def delete_import(import_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> None:
    """Forget an import that was never applied (its uploaded file too)."""
    imp = await _get(db, import_id)
    if imp.status == "applied":
        raise HTTPException(409, "Applied imports are kept as history")
    try:
        delete_object(imp.file_key)
    except Exception:  # noqa: BLE001 - the stored file may already be gone
        pass
    await db.delete(imp)
    await db.commit()
