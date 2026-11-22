"""Allow risks to be dismissed during review

Revision ID: b2f1c0d4e5a6
Revises: c1ca4505cd9f
Create Date: 2026-11-21
"""
from collections.abc import Sequence

from alembic import op

revision: str = "b2f1c0d4e5a6"
down_revision: str | None = "c1ca4505cd9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_risk_status"), "risk", type_="check")
    op.create_check_constraint(op.f("ck_risk_status"), "risk", "status IN ('suggested', 'open', 'mitigating', 'accepted', 'closed', 'dismissed')")


def downgrade() -> None:
    op.execute("UPDATE risk SET status = 'closed' WHERE status = 'dismissed'")
    op.drop_constraint(op.f("ck_risk_status"), "risk", type_="check")
    op.create_check_constraint(op.f("ck_risk_status"), "risk", "status IN ('suggested', 'open', 'mitigating', 'accepted', 'closed')")
