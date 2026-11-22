"""Notifications, background jobs and AI usage. These tables exist in the control database
(platform work) and in every company database (that company's work)."""

import uuid
from datetime import datetime

from sqlalchemy import Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, one_of
from app.models.common import fk, ts

JOB_TYPES = (
    "parse_framework",
    "generate_questions",
    "process_evidence",
    "generate_intake",
    "tailor_questions",
    "generate_outputs",
    "export_report",
    "cross_analyze",
)


class Notification(IdMixin, CreatedMixin, Base):
    __tablename__ = "notification"

    user_id: Mapped[uuid.UUID] = fk("app_user.id", ondelete="CASCADE")
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    read_at: Mapped[datetime | None] = ts()

    __table_args__ = (
        one_of(
            "type",
            (
                "assessment_deprecated",
                "domain_assigned",
                "changes_requested",
                "run_submitted",
                "run_approved",
            ),
        ),
        Index("ix_notification_user_unread", "user_id", "read_at"),
    )


class Job(IdMixin, CreatedMixin, Base):
    __tablename__ = "job"

    type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default="queued", nullable=False)
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[uuid.UUID | None] = mapped_column()
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    started_at: Mapped[datetime | None] = ts()
    finished_at: Mapped[datetime | None] = ts()

    __table_args__ = (
        one_of("type", JOB_TYPES),
        one_of("status", ("queued", "running", "done", "failed")),
        Index("ix_job_status_created", "status", "created_at"),
    )


class AiUsage(IdMixin, CreatedMixin, Base):
    """One row per AI call, for per-run budgets. Cost is estimated from list prices."""

    __tablename__ = "ai_usage"

    # Plain id, no foreign key: the control database has this table but no runs.
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    feature: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
