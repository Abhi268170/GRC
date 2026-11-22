"""Shared pieces for versioned entities (see SCHEMA.md §2).

A published version row is immutable; referencing it is a snapshot."""

import uuid
from datetime import datetime

from sqlalchemy import Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.models.base import VERSION_STATUS, one_of
from app.models.common import fk, ts


class VersionMixin:
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default="draft", nullable=False)
    published_at: Mapped[datetime | None] = ts()

    @declared_attr
    def published_by(cls) -> Mapped[uuid.UUID | None]:
        return fk("app_user.id", nullable=True)


def version_table_args(table: str, parent_col: str) -> tuple:
    """Constraints every <entity>_version table gets:
    unique version numbers, a valid status, one draft and one published version per entity."""
    return (
        UniqueConstraint(parent_col, "version"),
        one_of("status", VERSION_STATUS),
        Index(
            f"uq_{table}_one_draft",
            parent_col,
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
        Index(
            f"uq_{table}_one_published",
            parent_col,
            unique=True,
            postgresql_where=text("status = 'published'"),
        ),
    )
