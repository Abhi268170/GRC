"""Run outputs: roll-ups, action items, risks, report, and review comments."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, TimestampMixin, one_of
from app.models.common import fk, ts

ORIGIN = ("ai", "template", "manual")  # template = adapted by the AI from a requirement template


class RunRollup(IdMixin, Base):
    __tablename__ = "run_rollup"

    run_id: Mapped[uuid.UUID] = fk("assessment_run.id", ondelete="CASCADE")
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    ref_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    score: Mapped[float | None] = mapped_column(Numeric(4, 1))
    has_weakest_link: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("run_id", "level", "ref_id"),
        one_of("level", ("control", "domain", "assessment", "framework")),
    )


class ActionItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "action_item"

    run_id: Mapped[uuid.UUID | None] = fk("assessment_run.id", nullable=True, ondelete="SET NULL", index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), server_default="suggested", nullable=False)
    owner_id: Mapped[uuid.UUID | None] = fk("app_user.id", nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[uuid.UUID | None] = fk("app_user.id", nullable=True)

    __table_args__ = (
        one_of("status", ("suggested", "open", "in_progress", "done", "dismissed")),
        one_of("origin", ORIGIN),
    )


class ActionItemRequirement(Base):
    __tablename__ = "action_item_requirement"

    action_item_id: Mapped[uuid.UUID] = fk("action_item.id", ondelete="CASCADE", primary_key=True)
    requirement_version_id: Mapped[uuid.UUID] = fk("requirement_version.id", primary_key=True)


class Risk(IdMixin, TimestampMixin, Base):
    __tablename__ = "risk"

    run_id: Mapped[uuid.UUID | None] = fk("assessment_run.id", nullable=True, ondelete="SET NULL", index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(64))
    likelihood: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    impact: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score: Mapped[int] = mapped_column(SmallInteger, Computed("likelihood * impact", persisted=True))
    treatment: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="suggested", nullable=False)
    owner_id: Mapped[uuid.UUID | None] = fk("app_user.id", nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[uuid.UUID | None] = fk("app_user.id", nullable=True)

    __table_args__ = (
        CheckConstraint("likelihood BETWEEN 1 AND 5", name="likelihood_range"),
        CheckConstraint("impact BETWEEN 1 AND 5", name="impact_range"),
        CheckConstraint(
            "treatment IS NULL OR treatment IN ('mitigate', 'accept', 'transfer', 'avoid')",
            name="treatment",
        ),
        one_of("status", ("suggested", "open", "mitigating", "accepted", "closed", "dismissed")),
        one_of("origin", ORIGIN),
    )


class RiskRequirement(Base):
    __tablename__ = "risk_requirement"

    risk_id: Mapped[uuid.UUID] = fk("risk.id", ondelete="CASCADE", primary_key=True)
    requirement_version_id: Mapped[uuid.UUID] = fk("requirement_version.id", primary_key=True)


class Report(IdMixin, TimestampMixin, Base):
    __tablename__ = "report"

    run_id: Mapped[uuid.UUID] = fk("assessment_run.id", ondelete="CASCADE")
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default="draft", nullable=False)
    pdf_storage_key: Mapped[str | None] = mapped_column(Text)
    docx_storage_key: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = ts()

    __table_args__ = (UniqueConstraint("run_id"), one_of("status", ("draft", "final")))


class ReviewComment(IdMixin, CreatedMixin, Base):
    __tablename__ = "review_comment"

    run_id: Mapped[uuid.UUID] = fk("assessment_run.id", ondelete="CASCADE", index=True)
    run_domain_id: Mapped[uuid.UUID | None] = fk("run_domain.id", nullable=True, ondelete="CASCADE", index=True)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = fk("app_user.id")
    resolved_by: Mapped[uuid.UUID | None] = fk("app_user.id", nullable=True)
    resolved_at: Mapped[datetime | None] = ts()

    __table_args__ = (
        one_of("target_type", ("domain", "evaluation", "action_item", "risk", "report")),
    )
