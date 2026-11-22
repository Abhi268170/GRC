"""Version lifecycle helpers (SCHEMA.md §2): draft -> published -> deprecated.

Published rows are never edited. Changing published content means creating a new
draft (a copy of the current published version), editing it, and publishing it."""

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_version(db: AsyncSession, model: Any, parent_col: str, parent_id, status: str):
    return (
        await db.execute(
            select(model).where(getattr(model, parent_col) == parent_id, model.status == status)
        )
    ).scalar_one_or_none()


async def next_version_number(db: AsyncSession, model: Any, parent_col: str, parent_id) -> int:
    current = (
        await db.execute(
            select(func.max(model.version)).where(getattr(model, parent_col) == parent_id)
        )
    ).scalar()
    return (current or 0) + 1


async def require_draft(db: AsyncSession, model: Any, parent_col: str, parent_id):
    draft = await get_version(db, model, parent_col, parent_id, "draft")
    if draft is None:
        raise HTTPException(409, "There is no draft to change. Create a draft first.")
    return draft


async def publish(db: AsyncSession, model: Any, parent_col: str, parent_id, user_id):
    """Publish the draft and deprecate the previously published version. Returns
    (published, previously_published_or_None)."""
    draft = await require_draft(db, model, parent_col, parent_id)
    previous = await get_version(db, model, parent_col, parent_id, "published")
    if previous is not None:
        previous.status = "deprecated"
        await db.flush()  # free the one-published slot before publishing the draft
    draft.status = "published"
    draft.published_at = datetime.now(UTC)
    draft.published_by = user_id
    await db.flush()
    return draft, previous
