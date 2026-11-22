"""Assessments authored by the Super Admin. A published assessment_version is a snapshot:
it references immutable domain/control versions and owns its ordered questions."""

import uuid

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JOB_STATUS, Base, CreatedMixin, IdMixin, TimestampMixin, one_of
from app.models.common import fk
from app.models.versioning import VersionMixin, version_table_args


class Assessment(IdMixin, CreatedMixin, Base):
    __tablename__ = "assessment"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = fk("app_user.id", nullable=True)


class AssessmentVersion(IdMixin, VersionMixin, TimestampMixin, Base):
    __tablename__ = "assessment_version"

    assessment_id: Mapped[uuid.UUID] = fk("assessment.id", ondelete="CASCADE")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    generation_status: Mapped[str] = mapped_column(String(16), server_default="none", nullable=False)

    __table_args__ = (
        *version_table_args("assessment_version", "assessment_id"),
        one_of("generation_status", JOB_STATUS),
    )


class AssessmentVersionDomain(IdMixin, Base):
    __tablename__ = "assessment_version_domain"

    assessment_version_id: Mapped[uuid.UUID] = fk("assessment_version.id", ondelete="CASCADE")
    domain_version_id: Mapped[uuid.UUID] = fk("domain_version.id")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("assessment_version_id", "domain_version_id"),)


class AssessmentVersionControl(Base):
    __tablename__ = "assessment_version_control"

    assessment_version_id: Mapped[uuid.UUID] = fk(
        "assessment_version.id", ondelete="CASCADE", primary_key=True
    )
    control_version_id: Mapped[uuid.UUID] = fk("control_version.id", primary_key=True)
    assessment_version_domain_id: Mapped[uuid.UUID] = fk(
        "assessment_version_domain.id", ondelete="CASCADE", index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class Question(IdMixin, TimestampMixin, Base):
    __tablename__ = "question"

    assessment_version_id: Mapped[uuid.UUID] = fk("assessment_version.id", ondelete="CASCADE")
    assessment_version_domain_id: Mapped[uuid.UUID] = fk(
        "assessment_version_domain.id", ondelete="CASCADE"
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    help_text: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        one_of("origin", ("ai_generated", "ai_generated_edited", "manual")),
        Index(
            "ix_question_order", "assessment_version_id", "assessment_version_domain_id", "sort_order"
        ),
    )


class QuestionRequirement(Base):
    """Coverage tag: which requirements a question addresses."""

    __tablename__ = "question_requirement"

    question_id: Mapped[uuid.UUID] = fk("question.id", ondelete="CASCADE", primary_key=True)
    requirement_version_id: Mapped[uuid.UUID] = fk(
        "requirement_version.id", primary_key=True, index=True
    )
    source: Mapped[str] = mapped_column(String(16), server_default="ai", nullable=False)

    __table_args__ = (one_of("source", ("ai", "manual")),)
