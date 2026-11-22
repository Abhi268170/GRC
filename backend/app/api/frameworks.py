"""Frameworks (Super Admin manages; everyone can read published clauses)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.core.auth import ControlDB, CurrentUser, SuperAdmin
from app.core.queue import enqueue
from app.core.storage import delete_object, put_object
from app.models import Framework, FrameworkClause, FrameworkVersion, Job, RequirementClauseMap, RequirementVersion
from app.services import framework_parser
from app.services import versioning as v
from app.services.documents import ALLOWED, guess_type

router = APIRouter(prefix="/frameworks", tags=["frameworks"])

MAX_UPLOAD = 30 * 1024 * 1024


class VersionOut(BaseModel):
    id: uuid.UUID
    version: int
    version_label: str
    status: str
    parse_status: str
    parse_error: str | None
    clause_count: int
    published_at: datetime | None
    has_source: bool
    mapped_requirements: int  # requirement versions (in any control version) linked to this version's clauses


class FrameworkOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    publisher: str | None
    versions: list[VersionOut]
    mapped_requirements: int


class FrameworkCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9_-]*$")
    name: str = Field(min_length=2, max_length=200)
    publisher: str | None = None


class ClauseOut(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    ref: str
    title: str
    description: str | None
    level: int
    sort_order: int
    is_assessable: bool
    mapped_requirements: int


class VersionDetail(BaseModel):
    framework: FrameworkOut
    version: VersionOut
    clauses: list[ClauseOut]


class ClauseIn(BaseModel):
    ref: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1)
    description: str | None = None
    parent_ref: str | None = None
    is_assessable: bool = True


class ClauseSearchOut(BaseModel):
    id: uuid.UUID
    framework_code: str
    framework_name: str
    ref: str
    title: str


async def _versions(db: ControlDB, framework_id: uuid.UUID) -> list[VersionOut]:
    rows = (await db.execute(
        select(FrameworkVersion, func.count(FrameworkClause.id))
        .outerjoin(FrameworkClause, FrameworkClause.framework_version_id == FrameworkVersion.id)
        .where(FrameworkVersion.framework_id == framework_id)
        .group_by(FrameworkVersion.id)
        .order_by(FrameworkVersion.version.desc())
    )).all()
    mapped = dict((await db.execute(
        select(FrameworkClause.framework_version_id, func.count(func.distinct(RequirementClauseMap.requirement_version_id)))
        .join(RequirementClauseMap, RequirementClauseMap.framework_clause_id == FrameworkClause.id)
        .join(FrameworkVersion, FrameworkVersion.id == FrameworkClause.framework_version_id)
        .where(FrameworkVersion.framework_id == framework_id)
        .group_by(FrameworkClause.framework_version_id)
    )).all())
    return [VersionOut(id=fv.id, version=fv.version, version_label=fv.version_label, status=fv.status,
                       parse_status=fv.parse_status, parse_error=fv.parse_error, clause_count=n,
                       published_at=fv.published_at, has_source=bool(fv.source_storage_key),
                       mapped_requirements=mapped.get(fv.id, 0))
            for fv, n in rows]


async def _framework_out(db: ControlDB, fw: Framework) -> FrameworkOut:
    versions = await _versions(db, fw.id)
    return FrameworkOut(id=fw.id, code=fw.code, name=fw.name, publisher=fw.publisher, versions=versions,
                        mapped_requirements=sum(x.mapped_requirements for x in versions))


@router.get("", response_model=list[FrameworkOut])
async def list_frameworks(db: ControlDB, _: CurrentUser) -> list[FrameworkOut]:
    fws = (await db.execute(select(Framework).order_by(Framework.name))).scalars().all()
    return [await _framework_out(db, fw) for fw in fws]


@router.post("", response_model=FrameworkOut, status_code=201)
async def create_framework(body: FrameworkCreate, db: ControlDB, _: SuperAdmin) -> FrameworkOut:
    if (await db.execute(select(Framework.id).where(Framework.code == body.code))).first():
        raise HTTPException(409, f"Framework code {body.code} already exists")
    fw = Framework(code=body.code, name=body.name, publisher=body.publisher)
    db.add(fw)
    await db.commit()
    return await _framework_out(db, fw)


@router.post("/{framework_id}/versions", response_model=VersionOut, status_code=201)
async def upload_version(framework_id: uuid.UUID, db: ControlDB, _: SuperAdmin,
                         version_label: str = Form(min_length=1, max_length=40),
                         file: UploadFile = File(...)) -> VersionOut:
    """Upload a source document; creates a draft version and starts AI parsing."""
    fw = await db.get(Framework, framework_id)
    if fw is None:
        raise HTTPException(404, "Framework not found")
    if await v.get_version(db, FrameworkVersion, "framework_id", framework_id, "draft"):
        raise HTTPException(409, "This framework already has a draft version. Publish or discard it first.")
    data = await file.read()
    ctype = guess_type(file.filename or "document", file.content_type)
    if ctype not in ALLOWED or ctype.startswith("image/"):
        raise HTTPException(422, "Upload a PDF, DOCX, XLSX, CSV, Markdown, or text file")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 30 MB")

    fv = FrameworkVersion(framework_id=framework_id, status="draft", version_label=version_label,
                          version=await v.next_version_number(db, FrameworkVersion, "framework_id", framework_id),
                          parse_status="pending")
    db.add(fv)
    await db.flush()
    key = f"frameworks/{fw.code}/{fv.id}/{file.filename}"
    put_object(key, data, ctype)
    fv.source_storage_key = key
    await enqueue(db, type="parse_framework", ref_type="framework_version", ref_id=fv.id)
    return next(x for x in await _versions(db, framework_id) if x.id == fv.id)


@router.post("/versions/{version_id}/reparse", response_model=VersionOut)
async def reparse(version_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> VersionOut:
    fv = await db.get(FrameworkVersion, version_id)
    if fv is None or fv.status != "draft" or not fv.source_storage_key:
        raise HTTPException(409, "Only draft versions with a source document can be re-parsed")
    fv.parse_status, fv.parse_error = "pending", None
    await enqueue(db, type="parse_framework", ref_type="framework_version", ref_id=fv.id)
    return next(x for x in await _versions(db, fv.framework_id) if x.id == fv.id)


@router.get("/versions/{version_id}", response_model=VersionDetail)
async def get_version(version_id: uuid.UUID, db: ControlDB, _: CurrentUser) -> VersionDetail:
    fv = await db.get(FrameworkVersion, version_id)
    if fv is None:
        raise HTTPException(404, "Version not found")
    fw = await db.get(Framework, fv.framework_id)
    rows = (await db.execute(
        select(FrameworkClause, func.count(RequirementClauseMap.requirement_version_id))
        .outerjoin(RequirementClauseMap, RequirementClauseMap.framework_clause_id == FrameworkClause.id)
        .where(FrameworkClause.framework_version_id == version_id)
        .group_by(FrameworkClause.id)
        .order_by(FrameworkClause.sort_order)
    )).all()
    fw_out = await _framework_out(db, fw)
    return VersionDetail(
        framework=fw_out,
        version=next(x for x in fw_out.versions if x.id == version_id),
        clauses=[ClauseOut(id=c.id, parent_id=c.parent_id, ref=c.ref, title=c.title, description=c.description,
                           level=c.level, sort_order=c.sort_order, is_assessable=c.is_assessable,
                           mapped_requirements=n) for c, n in rows],
    )


@router.put("/versions/{version_id}/clauses", response_model=VersionDetail)
async def replace_clauses(version_id: uuid.UUID, body: list[ClauseIn], db: ControlDB, user: SuperAdmin) -> VersionDetail:
    fv = await db.get(FrameworkVersion, version_id)
    if fv is None or fv.status != "draft":
        raise HTTPException(409, "Only draft versions can be edited")
    await framework_parser.replace_clauses(db, fv, [c.model_dump() for c in body])
    await db.commit()
    return await get_version(version_id, db, user)


@router.post("/versions/{version_id}/publish", response_model=VersionOut)
async def publish_version(version_id: uuid.UUID, db: ControlDB, user: SuperAdmin) -> VersionOut:
    fv = await db.get(FrameworkVersion, version_id)
    if fv is None or fv.status != "draft":
        raise HTTPException(409, "Only a draft can be published")
    if fv.parse_status in ("pending", "processing"):
        raise HTTPException(409, "Wait for parsing to finish")
    if await framework_parser.clause_count(db, version_id) == 0:
        raise HTTPException(409, "A framework version needs at least one clause")
    await v.publish(db, FrameworkVersion, "framework_id", fv.framework_id, user.id)
    await db.commit()
    return next(x for x in await _versions(db, fv.framework_id) if x.id == version_id)


async def _mapping_block(db: ControlDB, version_ids: list[uuid.UUID]) -> None:
    """Published control versions never change, so clauses that requirements map to can't be removed."""
    n = (await db.execute(
        select(func.count(func.distinct(RequirementVersion.control_version_id)))
        .join(RequirementClauseMap, RequirementClauseMap.requirement_version_id == RequirementVersion.id)
        .join(FrameworkClause, FrameworkClause.id == RequirementClauseMap.framework_clause_id)
        .where(FrameworkClause.framework_version_id.in_(version_ids))
    )).scalar() or 0
    if n:
        raise HTTPException(409, f"Requirements in {n} control version{'s' if n != 1 else ''} map to these clauses, "
                                 "so it can't be deleted. Controls keep their mappings because published versions never change.")


async def _remove_versions(db: ControlDB, versions: list[FrameworkVersion]) -> None:
    ids = [fv.id for fv in versions]
    await db.execute(Job.__table__.delete().where(Job.ref_id.in_(ids), Job.status.in_(("queued", "running"))))
    for fv in versions:
        if fv.source_storage_key:
            try:
                delete_object(fv.source_storage_key)
            except Exception:  # noqa: BLE001 - a missing file shouldn't block the delete
                pass
        await db.delete(fv)


@router.delete("/versions/{version_id}", status_code=204)
async def delete_version(version_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> None:
    """Discard a draft, or delete a published/deprecated version that no requirement maps to."""
    fv = await db.get(FrameworkVersion, version_id)
    if fv is None:
        raise HTTPException(404, "Version not found")
    await _mapping_block(db, [fv.id])
    await _remove_versions(db, [fv])
    await db.commit()


@router.delete("/{framework_id}", status_code=204)
async def delete_framework(framework_id: uuid.UUID, db: ControlDB, _: SuperAdmin) -> None:
    """Delete a framework with all its versions and clauses, if no requirement maps to any of them."""
    fw = await db.get(Framework, framework_id)
    if fw is None:
        raise HTTPException(404, "Framework not found")
    versions = list((await db.execute(select(FrameworkVersion).where(FrameworkVersion.framework_id == framework_id))).scalars())
    await _mapping_block(db, [fv.id for fv in versions])
    await _remove_versions(db, versions)
    await db.flush()
    await db.delete(fw)
    await db.commit()


@router.get("/clauses/search", response_model=list[ClauseSearchOut])
async def search_clauses(db: ControlDB, _: CurrentUser, q: str = "", framework_id: uuid.UUID | None = None,
                         limit: int = 30) -> list[ClauseSearchOut]:
    """Published, assessable clauses for the requirement mapping picker."""
    stmt = (
        select(FrameworkClause, Framework)
        .join(FrameworkVersion, FrameworkVersion.id == FrameworkClause.framework_version_id)
        .join(Framework, Framework.id == FrameworkVersion.framework_id)
        .where(FrameworkVersion.status == "published", FrameworkClause.is_assessable)
    )
    if framework_id:
        stmt = stmt.where(Framework.id == framework_id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(FrameworkClause.ref.ilike(like), FrameworkClause.title.ilike(like)))
    rows = (await db.execute(stmt.order_by(Framework.code, FrameworkClause.sort_order).limit(min(limit, 100)))).all()
    return [ClauseSearchOut(id=c.id, framework_code=f.code, framework_name=f.name, ref=c.ref, title=c.title)
            for c, f in rows]
