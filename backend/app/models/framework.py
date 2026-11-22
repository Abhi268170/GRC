import uuid

from sqlalchemy import Boolean, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JOB_STATUS, Base, CreatedMixin, IdMixin, TimestampMixin, one_of
from app.models.common import fk
from app.models.versioning import VersionMixin, version_table_args


class Framework(IdMixin, CreatedMixin, Base):
    __tablename__ = "framework"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str | None] = mapped_column(Text)


class FrameworkVersion(IdMixin, VersionMixin, TimestampMixin, Base):
    __tablename__ = "framework_version"

    framework_id: Mapped[uuid.UUID] = fk("framework.id", ondelete="CASCADE")
    version_label: Mapped[str] = mapped_column(Text, nullable=False)
    source_storage_key: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(16), server_default="none", nullable=False)
    parse_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        *version_table_args("framework_version", "framework_id"),
        one_of("parse_status", JOB_STATUS),
    )


class FrameworkClause(IdMixin, Base):
    __tablename__ = "framework_clause"

    framework_version_id: Mapped[uuid.UUID] = fk("framework_version.id", ondelete="CASCADE")
    parent_id: Mapped[uuid.UUID | None] = fk("framework_clause.id", nullable=True, ondelete="CASCADE")
    ref: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_assessable: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)

    __table_args__ = (
        UniqueConstraint("framework_version_id", "ref"),
        Index("ix_framework_clause_tree", "framework_version_id", "parent_id", "sort_order"),
    )
