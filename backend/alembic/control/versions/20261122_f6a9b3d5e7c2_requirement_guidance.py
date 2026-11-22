"""Requirement guidance back (required), 'template' origin for action items and risks

Revision ID: f6a9b3d5e7c2
Revises: e5f8a2c3d4b1
Create Date: 2026-11-22
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a9b3d5e7c2"
down_revision: str | None = "e5f8a2c3d4b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows (if any) get an empty guidance; the API requires it from now on.
    op.add_column("requirement_version", sa.Column("guidance", sa.Text(), server_default="", nullable=False))
    op.alter_column("requirement_version", "guidance", server_default=None)
    for table in ("action_item", "risk"):
        op.drop_constraint(op.f(f"ck_{table}_origin"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_origin"), table, "origin IN ('ai', 'template', 'manual')")


def downgrade() -> None:
    for table in ("action_item", "risk"):
        op.execute(f"UPDATE {table} SET origin = 'ai' WHERE origin = 'template'")
        op.drop_constraint(op.f(f"ck_{table}_origin"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_origin"), table, "origin IN ('ai', 'manual')")
    op.drop_column("requirement_version", "guidance")
