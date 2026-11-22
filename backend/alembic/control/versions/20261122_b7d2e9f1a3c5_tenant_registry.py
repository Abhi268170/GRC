"""One database per company, step 1: the tenant registry and the login directory.

Adds where each company's database is (tenant.db_name, tenant.status) and which database
an email signs in to (login_directory). Nothing is removed yet: `python -m app.tenants migrate`
moves existing companies into their own databases before the next migration drops their tables.

Revision ID: b7d2e9f1a3c5
Revises: a1c4e6f8b2d9
Create Date: 2026-11-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d2e9f1a3c5"
down_revision: str | None = "a1c4e6f8b2d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("db_name", sa.Text(), nullable=True))
    op.add_column("tenant", sa.Column("status", sa.String(length=16), server_default="active", nullable=False))
    op.create_unique_constraint(op.f("uq_tenant_db_name"), "tenant", ["db_name"])
    op.create_check_constraint(op.f("ck_tenant_status"), "tenant", "status IN ('provisioning', 'active')")

    op.create_table(
        "login_directory",
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name=op.f("fk_login_directory_tenant_id_tenant"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("email", name=op.f("pk_login_directory")),
    )
    op.create_index(op.f("ix_login_directory_tenant_id"), "login_directory", ["tenant_id"])
    op.execute("INSERT INTO login_directory (email, tenant_id) SELECT lower(email), tenant_id FROM app_user")


def downgrade() -> None:
    op.drop_index(op.f("ix_login_directory_tenant_id"), table_name="login_directory")
    op.drop_table("login_directory")
    op.drop_constraint(op.f("ck_tenant_status"), "tenant", type_="check")
    op.drop_constraint(op.f("uq_tenant_db_name"), "tenant", type_="unique")
    op.drop_column("tenant", "status")
    op.drop_column("tenant", "db_name")
