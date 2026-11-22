"""Small helpers shared by model modules."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column


def fk(
    target: str,
    *,
    nullable: bool = False,
    ondelete: str | None = None,
    index: bool = False,
    primary_key: bool = False,
):
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        index=index,
        primary_key=primary_key,
    )


def ts(nullable: bool = True):
    return mapped_column(DateTime(timezone=True), nullable=nullable)


__all__ = ["fk", "ts", "uuid", "datetime"]
