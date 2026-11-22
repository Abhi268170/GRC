from sqlalchemy import Boolean, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, one_of

# Pick-lists the super admin maintains. Controls point at values, so renaming a value never
# changes what a control means; values are switched off, never deleted once used.
CONTROL_SINGLE_CATEGORIES = ("area", "company_risk_exposure")  # one value per control
CONTROL_MULTI_CATEGORIES = (  # several values per control
    "control_type",
    "protection_domain",
    "security_capability",
    "protection_objective",
    "use_case",
)
MASTER_DATA_CATEGORIES = (
    *CONTROL_SINGLE_CATEGORIES,
    *CONTROL_MULTI_CATEGORIES,
    "maturity_level",
    "risk_category",
    "likelihood",
    "impact",
    "action_priority",
)


class MasterDataItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "master_data_item"

    category: Mapped[str] = mapped_column(String(32), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    numeric_value: Mapped[float | None] = mapped_column(Numeric)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)

    __table_args__ = (
        UniqueConstraint("category", "code"),
        one_of("category", MASTER_DATA_CATEGORIES),
    )


ORG_ROLE_TYPES = ("executive", "operational")


class OrganisationalRole(IdMixin, TimestampMixin, Base):
    """Who is responsible for a control; also a user's role in their company."""

    __tablename__ = "organisational_role"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    abbreviation: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    reports_to: Mapped[str | None] = mapped_column(Text)  # plain text: not every manager is a listed role
    description: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str | None] = mapped_column(Text)
    accountabilities: Mapped[str | None] = mapped_column(Text)
    responsibilities: Mapped[str | None] = mapped_column(Text)
    decision_making_powers: Mapped[str | None] = mapped_column(Text)
    interfaces: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)

    __table_args__ = (one_of("type", ORG_ROLE_TYPES),)
