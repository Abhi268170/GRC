"""One database per company, step 2: company data leaves the control database.

Drops the run and output tables, the companies' users, jobs and AI usage, and every
tenant_id column. Each company's data now lives in its own database (see
TENANT_DATABASE_PLAN.md). This can't be undone by a downgrade.

Revision ID: c8e3f0a2b4d6
Revises: b7d2e9f1a3c5
Create Date: 2026-11-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e3f0a2b4d6"
down_revision: str | None = "b7d2e9f1a3c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "action_item", "action_item_requirement", "assessment_run", "conversation", "conversation_message",
    "evaluation_citation", "evidence", "report", "requirement_evaluation", "response", "response_evidence",
    "review_comment", "risk", "risk_requirement", "run_domain", "run_question", "run_rollup",
)


def upgrade() -> None:
    unmoved = op.get_bind().execute(sa.text("SELECT count(*) FROM tenant WHERE db_name IS NULL")).scalar()
    if unmoved:
        raise RuntimeError(
            f"{unmoved} company(ies) still live in the control database. "
            "Run `python -m app.tenants migrate`: it moves them to their own databases first."
        )

    # Company work: its rows were moved (users, notifications) or belong to runs that are gone.
    for table in ("job", "ai_usage", "notification"):
        op.execute(f"DELETE FROM {table} WHERE tenant_id IS NOT NULL")
    op.execute("DELETE FROM app_user WHERE tenant_id IS NOT NULL")

    op.drop_constraint("fk_ai_usage_run_id_assessment_run", "ai_usage", type_="foreignkey")
    op.execute("DROP TABLE " + ", ".join(TENANT_TABLES) + " CASCADE")

    # Dropping the column also drops its index, foreign key and the super-admin check on app_user.
    for table in ("app_user", "job", "ai_usage", "notification"):
        op.drop_column(table, "tenant_id")

    op.alter_column("tenant", "db_name", nullable=False)


def downgrade() -> None:
    raise NotImplementedError("Company data has moved to separate databases; restore from a backup instead.")
