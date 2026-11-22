"""AI framework parser: source document -> structured clause hierarchy in a DRAFT version.
The Super Admin reviews and edits the result before publishing."""

import asyncio
import uuid

import ai_contracts as contracts
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_object
from app.models import Framework, FrameworkClause, FrameworkVersion
from app.services import ai
from app.services.documents import file_input, guess_type


async def parse_version(db: AsyncSession, version_id: uuid.UUID) -> int:
    version = await db.get(FrameworkVersion, version_id)
    if version is None or version.status != "draft" or not version.source_storage_key:
        raise ai.AIError("Framework version is not a draft with a source document")
    framework = await db.get(Framework, version.framework_id)
    filename = version.source_storage_key.rsplit("/", 1)[-1]
    data = await asyncio.to_thread(get_object, version.source_storage_key)
    result = await ai.call(
        "/framework/parse",
        contracts.ParseFrameworkIn(framework_name=framework.name, version_label=version.version_label,
                                   file=file_input(data, guess_type(filename, None), filename)),
        contracts.ParsedFramework, ai.UsageTag("framework_parse"))
    return await replace_clauses(db, version, [c.model_dump() for c in result.clauses])


async def replace_clauses(db: AsyncSession, version: FrameworkVersion, clauses: list[dict]) -> int:
    """Replace all clauses of a draft version. Unknown parents become top-level; duplicate refs are dropped."""
    await db.execute(delete(FrameworkClause).where(FrameworkClause.framework_version_id == version.id))
    await db.flush()
    ids: dict[str, uuid.UUID] = {}
    levels: dict[str, int] = {}
    for order, c in enumerate(clauses):
        ref = c["ref"].strip()
        if not ref or ref in ids:
            continue
        parent = (c.get("parent_ref") or "").strip() or None
        parent_id = ids.get(parent) if parent else None
        level = levels[parent] + 1 if parent_id else 0
        row = FrameworkClause(
            framework_version_id=version.id, parent_id=parent_id, ref=ref, title=c["title"].strip(),
            description=(c.get("description") or "").strip() or None, level=level, sort_order=order,
            is_assessable=bool(c.get("is_assessable", True)),
        )
        db.add(row)
        await db.flush()
        ids[ref], levels[ref] = row.id, level
    return len(ids)


async def clause_count(db: AsyncSession, version_id: uuid.UUID) -> int:
    return len((await db.execute(select(FrameworkClause.id).where(FrameworkClause.framework_version_id == version_id))).all())
