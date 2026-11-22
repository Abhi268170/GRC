import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, one_of
from app.models.common import fk, ts

PLATFORM_ROLES = ("super_admin", "tenant_admin", "tenant_user")
EMPLOYEE_RANGES = ("1-10", "11-50", "51-200", "201-1000", "1000+")
TENANT_STATUS = ("provisioning", "active")


class Tenant(IdMixin, TimestampMixin, Base):
    """Registry of companies. Lives in the control database only."""

    __tablename__ = "tenant"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    industry: Mapped[str | None] = mapped_column(Text)
    employee_count: Mapped[str | None] = mapped_column(String(16))
    profile: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    # The company's own database on the same Postgres server.
    db_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default="active", nullable=False)

    __table_args__ = (
        one_of("status", TENANT_STATUS),
        CheckConstraint(
            "employee_count IS NULL OR employee_count IN ("
            + ", ".join(f"'{v}'" for v in EMPLOYEE_RANGES)
            + ")",
            name="employee_count",
        ),
    )


class LoginDirectory(Base):
    """Which database an email signs in to. Lives in the control database only; it also keeps
    emails unique across all companies. tenant_id is empty for the super admin."""

    __tablename__ = "login_directory"

    email: Mapped[str] = mapped_column(Text, primary_key=True)  # lower case
    tenant_id: Mapped[uuid.UUID | None] = fk("tenant.id", nullable=True, ondelete="CASCADE", index=True)


class AppUser(IdMixin, TimestampMixin, Base):
    """Users of one database: the super admin in the control database, a company's users in its own."""

    __tablename__ = "app_user"

    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    platform_role: Mapped[str] = mapped_column(String(32), nullable=False)
    organisational_role_id: Mapped[uuid.UUID | None] = fk("organisational_role.id", nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    last_login_at: Mapped[datetime | None] = ts()

    __table_args__ = (one_of("platform_role", PLATFORM_ROLES),)
