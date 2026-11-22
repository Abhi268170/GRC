"""AI framework parser: source document -> structured clause hierarchy in a DRAFT version.
The Super Admin reviews and edits the result before publishing."""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_object
from app.models import Framework, FrameworkClause, FrameworkVersion
from app.services import ai
from app.services.documents import guess_type, to_content_blocks


class ParsedClause(BaseModel):
    ref: str = Field(description="The identifier exactly as written in the document, e.g. 'PR.AA-01' or 'A.5.15'.")
    title: str = Field(description="Clause title or, for clauses without a title, the full statement.")
    description: str | None = Field(description="Supporting text for the clause, if any. Null if none.")
    parent_ref: str | None = Field(description="ref of the parent clause; null for top-level items.")
    is_assessable: bool = Field(description="True for clauses an organisation can be assessed against; false for pure grouping headings (chapters, functions, categories).")


class ParsedFramework(BaseModel):
    clauses: list[ParsedClause]


SYSTEM = """You convert compliance and security framework documents into a structured clause hierarchy.

Rules:
- Extract every requirement-bearing clause (controls, subcategories, numbered requirements) and every grouping heading above them (chapters, functions, categories, sections).
- Keep refs exactly as the document writes them. Never invent refs; if a grouping has no ref, derive a short one from its parent and position and keep it stable.
- List clauses in document order, parents before their children.
- Omit front matter, forewords, glossaries, bibliographies, change logs and informative examples or references to other documents.
- Titles are concise; put longer explanatory text in description."""


async def parse_version(db: AsyncSession, version_id: uuid.UUID) -> int:
    version = await db.get(FrameworkVersion, version_id)
    if version is None or version.status != "draft" or not version.source_storage_key:
        raise ai.AIError("Framework version is not a draft with a source document")
    framework = await db.get(Framework, version.framework_id)
    filename = version.source_storage_key.rsplit("/", 1)[-1]
    data = get_object(version.source_storage_key)
    blocks = to_content_blocks(data, guess_type(filename, None), filename)
    blocks.append({"type": "text", "text": f"Framework: {framework.name} ({version.version_label}). Extract its clause hierarchy."})

    result = await ai.structured(output=ParsedFramework, system=SYSTEM, content=blocks, effort="medium",
                                 usage=ai.UsageTag("framework_parse"))
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
