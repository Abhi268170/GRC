"""Control import batches (Excel import of the control library)

Revision ID: a1c4e6f8b2d9
Revises: f6a9b3d5e7c2
Create Date: 2026-11-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a1c4e6f8b2d9"
down_revision: str | None = "f6a9b3d5e7c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "control_import",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="preview", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        *[sa.Column(c, postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False)
          for c in ("summary", "report", "choices", "fingerprints")],
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('preview', 'applied', 'expired')", name=op.f("ck_control_import_status")),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], name=op.f("fk_control_import_created_by_app_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_control_import")),
    )
    op.add_column("control_version", sa.Column("import_id", sa.UUID(), nullable=True))
    op.create_foreign_key(op.f("fk_control_version_import_id_control_import"), "control_version", "control_import",
                          ["import_id"], ["id"], ondelete="SET NULL")
    op.create_index(op.f("ix_control_version_import_id"), "control_version", ["import_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_control_version_import_id"), "control_version")
    op.drop_column("control_version", "import_id")
    op.drop_table("control_import")
