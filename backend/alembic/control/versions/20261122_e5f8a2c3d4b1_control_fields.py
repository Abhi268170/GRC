"""Full control fields: classification master data, organisational roles, requirement evidence and templates

Wipes the control library, assessments and runs (POC test data): codes, domains and requirement
guidance all change shape, so the old rows can't be carried over. Accounts, tenants and frameworks stay.

Revision ID: e5f8a2c3d4b1
Revises: d4e7a9b1c2f3
Create Date: 2026-11-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e5f8a2c3d4b1"
down_revision: str | None = "d4e7a9b1c2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_CATEGORIES = ("job_role", "maturity_level", "risk_category", "likelihood", "impact", "action_priority")
NEW_CATEGORIES = ("area", "company_risk_exposure", "control_type", "protection_domain", "security_capability",
                  "protection_objective", "use_case", "maturity_level", "risk_category", "likelihood", "impact",
                  "action_priority")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # --- wipe test data that depends on the old library shape ---
    op.execute("TRUNCATE assessment, domain, control CASCADE")
    op.execute("DELETE FROM job WHERE ref_type IN ('assessment_run', 'assessment_version', 'evidence')")
    op.execute("DELETE FROM notification")

    # --- organisational roles (replace the job_role master data list) ---
    op.create_table(
        "organisational_role",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("abbreviation", sa.String(length=16), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("reports_to", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("accountabilities", sa.Text(), nullable=True),
        sa.Column("responsibilities", sa.Text(), nullable=True),
        sa.Column("decision_making_powers", sa.Text(), nullable=True),
        sa.Column("interfaces", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("type IN ('executive', 'operational')", name=op.f("ck_organisational_role_type")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organisational_role")),
        sa.UniqueConstraint("code", name=op.f("uq_organisational_role_code")),
        sa.UniqueConstraint("abbreviation", name=op.f("uq_organisational_role_abbreviation")),
    )
    op.drop_column("app_user", "job_role_id")
    op.add_column("app_user", sa.Column("organisational_role_id", sa.UUID(), nullable=True))
    op.create_foreign_key(op.f("fk_app_user_organisational_role_id_organisational_role"), "app_user",
                          "organisational_role", ["organisational_role_id"], ["id"])

    # --- master data lists ---
    op.execute("DELETE FROM master_data_item WHERE category = 'job_role'")
    op.drop_constraint(op.f("ck_master_data_item_category"), "master_data_item", type_="check")
    op.create_check_constraint(op.f("ck_master_data_item_category"), "master_data_item",
                               f"category IN ({_in(NEW_CATEGORIES)})")

    # --- domain: the stable code is the abbreviation used in control codes ---
    op.alter_column("domain", "code", new_column_name="abbreviation", type_=sa.String(length=16))
    op.execute("ALTER TABLE domain RENAME CONSTRAINT uq_domain_code TO uq_domain_abbreviation")

    # --- control version fields ---
    op.alter_column("control_version", "description", new_column_name="short_description")
    for col in ("area_id", "company_risk_exposure_id"):
        op.add_column("control_version", sa.Column(col, sa.UUID(), nullable=True))
        op.create_foreign_key(op.f(f"fk_control_version_{col}_master_data_item"), "control_version",
                              "master_data_item", [col], ["id"])
    op.add_column("control_version", sa.Column("responsible_role_id", sa.UUID(), nullable=True))
    op.create_foreign_key(op.f("fk_control_version_responsible_role_id_organisational_role"), "control_version",
                          "organisational_role", ["responsible_role_id"], ["id"])
    for col in ("key_requirement", "risk_exposure", "involved_parties", "triggers", "supporting_documents",
                "special_considerations", "subject_specific_support"):
        op.add_column("control_version", sa.Column(col, sa.Text(), nullable=True))
    op.create_table(
        "control_version_classification",
        sa.Column("control_version_id", sa.UUID(), nullable=False),
        sa.Column("master_data_item_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["control_version_id"], ["control_version.id"], ondelete="CASCADE",
                                name=op.f("fk_control_version_classification_control_version_id_control_version")),
        sa.ForeignKeyConstraint(["master_data_item_id"], ["master_data_item.id"],
                                name=op.f("fk_control_version_classification_master_data_item_id_master_data_item")),
        sa.PrimaryKeyConstraint("control_version_id", "master_data_item_id",
                                name=op.f("pk_control_version_classification")),
    )
    op.create_index(op.f("ix_control_version_classification_master_data_item_id"),
                    "control_version_classification", ["master_data_item_id"])

    # --- requirement version fields (guidance is replaced by evidence lines) ---
    op.drop_column("requirement_version", "guidance")
    op.add_column("requirement_version", sa.Column("mandatory", sa.Boolean(), nullable=True))
    for col in ("evidence", "action_templates", "risk_templates"):
        op.add_column("requirement_version",
                      sa.Column(col, postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False))


def downgrade() -> None:
    for col in ("evidence", "action_templates", "risk_templates", "mandatory"):
        op.drop_column("requirement_version", col)
    op.add_column("requirement_version", sa.Column("guidance", sa.Text(), nullable=True))
    op.drop_index(op.f("ix_control_version_classification_master_data_item_id"), "control_version_classification")
    op.drop_table("control_version_classification")
    for col in ("key_requirement", "risk_exposure", "involved_parties", "triggers", "supporting_documents",
                "special_considerations", "subject_specific_support", "responsible_role_id", "area_id",
                "company_risk_exposure_id"):
        op.drop_column("control_version", col)
    op.alter_column("control_version", "short_description", new_column_name="description")
    op.execute("ALTER TABLE domain RENAME CONSTRAINT uq_domain_abbreviation TO uq_domain_code")
    op.alter_column("domain", "abbreviation", new_column_name="code", type_=sa.String(length=64))
    op.execute(f"DELETE FROM master_data_item WHERE category NOT IN ({_in(OLD_CATEGORIES)})")
    op.drop_constraint(op.f("ck_master_data_item_category"), "master_data_item", type_="check")
    op.create_check_constraint(op.f("ck_master_data_item_category"), "master_data_item",
                               f"category IN ({_in(OLD_CATEGORIES)})")
    op.drop_column("app_user", "organisational_role_id")
    op.add_column("app_user", sa.Column("job_role_id", sa.UUID(), nullable=True))
    op.create_foreign_key(op.f("fk_app_user_job_role_id_master_data_item"), "app_user", "master_data_item",
                          ["job_role_id"], ["id"])
    op.drop_table("organisational_role")
