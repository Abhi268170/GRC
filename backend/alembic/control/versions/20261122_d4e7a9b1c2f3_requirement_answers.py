"""Per-requirement answers, awaiting-AI status, cross-analysis job type

Revision ID: d4e7a9b1c2f3
Revises: 1c8a1f5a4af3
Create Date: 2026-11-22
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e7a9b1c2f3"
down_revision: str | None = "1c8a1f5a4af3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_TYPES = ("parse_framework", "generate_questions", "process_evidence", "generate_intake",
             "tailor_questions", "generate_outputs", "export_report")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.add_column("requirement_evaluation", sa.Column("answer", sa.Text(), nullable=True))
    op.drop_constraint(op.f("ck_requirement_evaluation_status"), "requirement_evaluation", type_="check")
    op.create_check_constraint(op.f("ck_requirement_evaluation_status"), "requirement_evaluation",
                               "status IN ('awaiting_ai', 'ai_suggested', 'verified', 'overridden')")
    op.drop_constraint(op.f("ck_requirement_evaluation_na_xor_rating"), "requirement_evaluation", type_="check")
    op.create_check_constraint(op.f("ck_requirement_evaluation_na_xor_rating"), "requirement_evaluation",
                               "(status = 'awaiting_ai' AND rating IS NULL AND NOT is_na) OR "
                               "(status <> 'awaiting_ai' AND is_na = (rating IS NULL))")
    op.drop_constraint(op.f("ck_job_type"), "job", type_="check")
    op.create_check_constraint(op.f("ck_job_type"), "job", f"type IN ({_in(JOB_TYPES + ('cross_analyze',))})")


def downgrade() -> None:
    op.execute("DELETE FROM job WHERE type = 'cross_analyze'")
    op.drop_constraint(op.f("ck_job_type"), "job", type_="check")
    op.create_check_constraint(op.f("ck_job_type"), "job", f"type IN ({_in(JOB_TYPES)})")
    op.execute("DELETE FROM requirement_evaluation WHERE status = 'awaiting_ai'")
    op.drop_constraint(op.f("ck_requirement_evaluation_na_xor_rating"), "requirement_evaluation", type_="check")
    op.create_check_constraint(op.f("ck_requirement_evaluation_na_xor_rating"), "requirement_evaluation", "is_na = (rating IS NULL)")
    op.drop_constraint(op.f("ck_requirement_evaluation_status"), "requirement_evaluation", type_="check")
    op.create_check_constraint(op.f("ck_requirement_evaluation_status"), "requirement_evaluation",
                               "status IN ('ai_suggested', 'verified', 'overridden')")
    op.drop_column("requirement_evaluation", "answer")
