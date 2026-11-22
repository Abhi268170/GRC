"""Control library: domains, controls, requirements, and clause mappings."""

import uuid

from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, TimestampMixin, one_of
from app.models.common import fk, ts
from app.models.versioning import VersionMixin, version_table_args


class Domain(IdMixin, CreatedMixin, Base):
    __tablename__ = "domain"

    # Stable short code, e.g. IAM. It starts every control code in the domain, so it never changes.
    abbreviation: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)


class DomainVersion(IdMixin, VersionMixin, TimestampMixin, Base):
    __tablename__ = "domain_version"

    domain_id: Mapped[uuid.UUID] = fk("domain.id", ondelete="CASCADE")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = version_table_args("domain_version", "domain_id")


class Control(IdMixin, CreatedMixin, Base):
    """Stable control identity. code = domain abbreviation + 2-digit number in the domain (IAM02);
    a version is shown as code + "." + 4-digit version number (IAM02.0001)."""

    __tablename__ = "control"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


class ControlVersion(IdMixin, VersionMixin, TimestampMixin, Base):
    """Immutable once published, together with its requirement versions and clause mappings."""

    __tablename__ = "control_version"

    control_id: Mapped[uuid.UUID] = fk("control.id", ondelete="CASCADE")
    domain_id: Mapped[uuid.UUID] = fk("domain.id", index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)

    # Classification (master data). Several-per-control lists live in control_version_classification.
    area_id: Mapped[uuid.UUID | None] = fk("master_data_item.id", nullable=True)
    company_risk_exposure_id: Mapped[uuid.UUID | None] = fk("master_data_item.id", nullable=True)
    responsible_role_id: Mapped[uuid.UUID | None] = fk("organisational_role.id", nullable=True)

    short_description: Mapped[str | None] = mapped_column(Text)        # why the control is important
    key_requirement: Mapped[str | None] = mapped_column(Text)          # one sentence: what must be in place
    risk_exposure: Mapped[str | None] = mapped_column(Text)            # impact if not implemented
    involved_parties: Mapped[str | None] = mapped_column(Text)
    triggers: Mapped[str | None] = mapped_column(Text)
    supporting_documents: Mapped[str | None] = mapped_column(Text)
    special_considerations: Mapped[str | None] = mapped_column(Text)
    subject_specific_support: Mapped[str | None] = mapped_column(Text)

    # Set when an Excel import created this draft (for "publish all from this import" and history).
    import_id: Mapped[uuid.UUID | None] = fk("control_import.id", nullable=True, ondelete="SET NULL", index=True)

    __table_args__ = version_table_args("control_version", "control_id")


class ControlVersionClassification(Base):
    """Several-per-control master data values (control type, protection domain, security capability,
    protection objective, use case). The value's category says which list it belongs to."""

    __tablename__ = "control_version_classification"

    control_version_id: Mapped[uuid.UUID] = fk("control_version.id", ondelete="CASCADE", primary_key=True)
    master_data_item_id: Mapped[uuid.UUID] = fk("master_data_item.id", primary_key=True, index=True)


class Requirement(IdMixin, CreatedMixin, Base):
    """Stable identity of a requirement across control versions."""

    __tablename__ = "requirement"

    control_id: Mapped[uuid.UUID] = fk("control.id", ondelete="CASCADE", index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


class RequirementVersion(IdMixin, Base):
    __tablename__ = "requirement_version"

    requirement_id: Mapped[uuid.UUID] = fk("requirement.id", ondelete="CASCADE")
    control_version_id: Mapped[uuid.UUID] = fk("control_version.id", ondelete="CASCADE", index=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    guidance: Mapped[str] = mapped_column(Text, nullable=False)  # how to meet it (evidence is what proves it)
    mandatory: Mapped[bool | None] = mapped_column(Boolean)  # yes / no / not set; no effect on scoring yet
    # What can be checked to show the requirement is met: ["Signed policy", ...]
    evidence: Mapped[list] = mapped_column(JSONB, server_default="[]", nullable=False)
    # [{"title": ..., "description": ...}]: the measure to take / the risk if the requirement isn't met
    action_templates: Mapped[list] = mapped_column(JSONB, server_default="[]", nullable=False)
    risk_templates: Mapped[list] = mapped_column(JSONB, server_default="[]", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("control_version_id", "requirement_id"),)


class RequirementClauseMap(Base):
    __tablename__ = "requirement_clause_map"

    requirement_version_id: Mapped[uuid.UUID] = fk(
        "requirement_version.id", ondelete="CASCADE", primary_key=True
    )
    framework_clause_id: Mapped[uuid.UUID] = fk(
        "framework_clause.id", ondelete="CASCADE", primary_key=True, index=True
    )
    source: Mapped[str] = mapped_column(String(16), server_default="manual", nullable=False)

    __table_args__ = (one_of("source", ("manual", "ai_suggested", "ai_confirmed")),)


CONTROL_IMPORT_STATUS = ("preview", "applied", "expired")


class ControlImport(IdMixin, CreatedMixin, Base):
    """One upload of the control workbook: previewed first (nothing written), then applied in one transaction."""

    __tablename__ = "control_import"

    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_key: Mapped[str] = mapped_column(Text, nullable=False)  # the uploaded workbook in object storage
    status: Mapped[str] = mapped_column(String(16), server_default="preview", nullable=False)
    created_by: Mapped[uuid.UUID] = fk("app_user.id")
    applied_at: Mapped[datetime | None] = ts()
    summary: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)   # counts
    report: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)    # errors, warnings, diffs
    choices: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)   # conflicts + removals
    fingerprints: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)  # re-checked on apply

    __table_args__ = (one_of("status", CONTROL_IMPORT_STATUS),)
