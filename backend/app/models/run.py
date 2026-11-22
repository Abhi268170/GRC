"""Tenant assessment runs: tailored questions, responses, evidence, evaluations, conversations."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, TimestampMixin, one_of
from app.models.common import fk, ts

RUN_STATUS = ("intake", "in_progress", "generating_outputs", "in_review", "changes_requested", "approved")


class AssessmentRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "assessment_run"

    assessment_version_id: Mapped[uuid.UUID] = fk("assessment_version.id", index=True)
    title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), server_default="intake", nullable=False)
    started_by: Mapped[uuid.UUID] = fk("app_user.id")
    started_at: Mapped[datetime | None] = ts()
    submitted_at: Mapped[datetime | None] = ts()
    approved_by: Mapped[uuid.UUID | None] = fk("app_user.id", nullable=True)
    approved_at: Mapped[datetime | None] = ts()
    intake_summary: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (one_of("status", RUN_STATUS),)


class RunDomain(IdMixin, TimestampMixin, Base):
    __tablename__ = "run_domain"

    run_id: Mapped[uuid.UUID] = fk("assessment_run.id", ondelete="CASCADE")
    assessment_version_domain_id: Mapped[uuid.UUID] = fk("assessment_version_domain.id")
    assignee_id: Mapped[uuid.UUID | None] = fk("app_user.id", nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), server_default="not_started", nullable=False)
    completed_by: Mapped[uuid.UUID | None] = fk("app_user.id", nullable=True)
    completed_at: Mapped[datetime | None] = ts()

    __table_args__ = (
        UniqueConstraint("run_id", "assessment_version_domain_id"),
        one_of("status", ("not_started", "in_progress", "completed", "changes_requested")),
    )


class RunQuestion(IdMixin, TimestampMixin, Base):
    """Per-run copy of a base question (tailored wording/order) or an AI follow-up."""

    __tablename__ = "run_question"

    run_id: Mapped[uuid.UUID] = fk("assessment_run.id", ondelete="CASCADE")
    run_domain_id: Mapped[uuid.UUID] = fk("run_domain.id", ondelete="CASCADE", index=True)
    question_id: Mapped[uuid.UUID | None] = fk("question.id", nullable=True)
    parent_run_question_id: Mapped[uuid.UUID | None] = fk(
        "run_question.id", nullable=True, ondelete="CASCADE"
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    proposed_na: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    proposed_na_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="pending", nullable=False)

    __table_args__ = (
        one_of("kind", ("base", "follow_up")),
        one_of("status", ("pending", "answered", "skipped_na")),
        CheckConstraint(
            "(kind = 'base' AND question_id IS NOT NULL AND parent_run_question_id IS NULL) OR "
            "(kind = 'follow_up' AND parent_run_question_id IS NOT NULL)",
            name="kind_links",
        ),
        Index("ix_run_question_order", "run_id", "run_domain_id", "sort_order"),
    )


class Response(IdMixin, Base):
    __tablename__ = "response"

    run_id: Mapped[uuid.UUID] = fk("assessment_run.id", ondelete="CASCADE", index=True)
    run_question_id: Mapped[uuid.UUID] = fk("run_question.id", ondelete="CASCADE")
    answer_text: Mapped[str | None] = mapped_column(Text)
    is_na: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    na_reason: Mapped[str | None] = mapped_column(Text)
    answered_by: Mapped[uuid.UUID] = fk("app_user.id")
    answered_at: Mapped[datetime | None] = ts()
    updated_at: Mapped[datetime | None] = ts()

    __table_args__ = (
        UniqueConstraint("run_question_id"),
        CheckConstraint("NOT is_na OR na_reason IS NOT NULL", name="na_requires_reason"),
    )


class Evidence(IdMixin, TimestampMixin, Base):
    __tablename__ = "evidence"

    run_id: Mapped[uuid.UUID] = fk("assessment_run.id", ondelete="CASCADE")
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(16), server_default="pending", nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    processing_error: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID] = fk("app_user.id")

    __table_args__ = (
        UniqueConstraint("run_id", "sha256"),  # same file in a run is processed only once
        one_of("processing_status", ("pending", "processing", "ready", "failed")),
    )


class ResponseEvidence(Base):
    __tablename__ = "response_evidence"

    response_id: Mapped[uuid.UUID] = fk("response.id", ondelete="CASCADE", primary_key=True)
    evidence_id: Mapped[uuid.UUID] = fk(
        "evidence.id", ondelete="CASCADE", primary_key=True, index=True
    )


class RequirementEvaluation(IdMixin, TimestampMixin, Base):
    __tablename__ = "requirement_evaluation"

    run_id: Mapped[uuid.UUID] = fk("assessment_run.id", ondelete="CASCADE")
    requirement_version_id: Mapped[uuid.UUID] = fk("requirement_version.id")
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    is_na: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    na_reason: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)  # a person's own answer for this requirement
    ai_rating: Mapped[int | None] = mapped_column(SmallInteger)
    ai_is_na: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(16), server_default="ai_suggested", nullable=False)
    verified_by: Mapped[uuid.UUID | None] = fk("app_user.id", nullable=True)
    verified_at: Mapped[datetime | None] = ts()

    __table_args__ = (
        UniqueConstraint("run_id", "requirement_version_id"),
        one_of("status", ("awaiting_ai", "ai_suggested", "verified", "overridden")),
        CheckConstraint("rating IS NULL OR rating BETWEEN 0 AND 4", name="rating_range"),
        CheckConstraint("ai_rating IS NULL OR ai_rating BETWEEN 0 AND 4", name="ai_rating_range"),
        # awaiting_ai: a person gave an answer/evidence without a rating; the AI rates it next.
        CheckConstraint("(status = 'awaiting_ai' AND rating IS NULL AND NOT is_na) OR "
                        "(status <> 'awaiting_ai' AND is_na = (rating IS NULL))", name="na_xor_rating"),
        CheckConstraint("NOT is_na OR na_reason IS NOT NULL", name="na_requires_reason"),
        Index("ix_requirement_evaluation_run_status", "run_id", "status"),
    )


class EvaluationCitation(IdMixin, Base):
    __tablename__ = "evaluation_citation"

    evaluation_id: Mapped[uuid.UUID] = fk(
        "requirement_evaluation.id", ondelete="CASCADE", index=True
    )
    response_id: Mapped[uuid.UUID | None] = fk("response.id", nullable=True, ondelete="CASCADE", index=True)
    evidence_id: Mapped[uuid.UUID | None] = fk("evidence.id", nullable=True, ondelete="CASCADE", index=True)
    excerpt: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("response_id IS NOT NULL OR evidence_id IS NOT NULL", name="has_source"),
    )


class Conversation(IdMixin, TimestampMixin, Base):
    __tablename__ = "conversation"

    run_id: Mapped[uuid.UUID] = fk("assessment_run.id", ondelete="CASCADE", index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    run_domain_id: Mapped[uuid.UUID | None] = fk("run_domain.id", nullable=True, ondelete="CASCADE", index=True)
    state: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)

    __table_args__ = (
        one_of("kind", ("intake", "domain")),
        CheckConstraint("(kind = 'domain') = (run_domain_id IS NOT NULL)", name="domain_link"),
    )


class ConversationMessage(IdMixin, CreatedMixin, Base):
    __tablename__ = "conversation_message"

    conversation_id: Mapped[uuid.UUID] = fk("conversation.id", ondelete="CASCADE", index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONB)
    author_id: Mapped[uuid.UUID | None] = fk("app_user.id", nullable=True)

    __table_args__ = (one_of("role", ("user", "assistant", "system_event")),)
