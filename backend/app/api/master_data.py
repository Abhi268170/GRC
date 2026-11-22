import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.schemas import ORM
from app.core.auth import ControlDB, CurrentUser, SuperAdmin
from app.core.queue import enqueue_task
from app.models import MasterDataItem, OrganisationalRole
from app.models.master_data import MASTER_DATA_CATEGORIES, ORG_ROLE_TYPES

router = APIRouter(prefix="/master-data", tags=["master data"])

# Categories whose codes/values are relied on by scoring and must not be edited structurally.
LOCKED = {"maturity_level", "likelihood", "impact"}


class CategoryOut(BaseModel):
    key: str
    label: str
    group: str
    description: str
    selection: str  # how a control uses it: "one", "one_optional", "several", or "" when not on controls
    locked: bool


# Display metadata for the admin screens, grouped for navigation. Order here is display order.
CATEGORIES: list[CategoryOut] = [
    CategoryOut(key="area", label="Area", group="Control classification", selection="one", locked=False,
                description="Which kind of measure a control is."),
    CategoryOut(key="control_type", label="Control type", group="Control classification", selection="several",
                locked=False, description="How a control works."),
    CategoryOut(key="protection_domain", label="Protection domain", group="Control classification", selection="several",
                locked=False, description="Where a control works (the NIST CSF functions)."),
    CategoryOut(key="security_capability", label="Security capability", group="Control classification",
                selection="several", locked=False, description="The security capability a control builds."),
    CategoryOut(key="protection_objective", label="Protection objective", group="Control classification",
                selection="several", locked=False, description="What a control protects."),
    CategoryOut(key="use_case", label="Use case", group="Control classification", selection="several", locked=False,
                description="What a control applies to."),
    CategoryOut(key="company_risk_exposure", label="Company risk exposure", group="Control classification",
                selection="one_optional", locked=False, description="How exposed a company is if the control is missing."),
    CategoryOut(key="maturity_level", label="Maturity levels", group="Assessment & scoring", selection="", locked=True,
                description="The rating scale for requirements. Fixed, because scoring depends on it."),
    CategoryOut(key="risk_category", label="Risk categories", group="Risks & actions", selection="", locked=False,
                description="Groups risks in the risk register."),
    CategoryOut(key="likelihood", label="Likelihood", group="Risks & actions", selection="", locked=True,
                description="Risk likelihood scale, 1 to 5. Fixed, because risk scores depend on it."),
    CategoryOut(key="impact", label="Impact", group="Risks & actions", selection="", locked=True,
                description="Risk impact scale, 1 to 5. Fixed, because risk scores depend on it."),
    CategoryOut(key="action_priority", label="Action priority", group="Risks & actions", selection="", locked=False,
                description="Priority of action items."),
]
assert {c.key for c in CATEGORIES} == set(MASTER_DATA_CATEGORIES)


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(_: SuperAdmin) -> list[CategoryOut]:
    return CATEGORIES


class ItemOut(ORM):
    id: uuid.UUID
    category: str
    code: str
    label: str
    description: str | None
    numeric_value: float | None
    sort_order: int
    is_active: bool


class ItemCreate(BaseModel):
    category: str
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ItemEdit(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    description: str | None = None
    is_active: bool = True


@router.get("", response_model=list[ItemOut])
async def list_items(db: ControlDB, _: SuperAdmin, category: str | None = None) -> list[MasterDataItem]:
    stmt = select(MasterDataItem).order_by(MasterDataItem.category, MasterDataItem.sort_order)
    if category:
        stmt = stmt.where(MasterDataItem.category == category)
    return list((await db.execute(stmt)).scalars())


@router.post("", response_model=ItemOut, status_code=201)
async def create_item(body: ItemCreate, db: ControlDB, _: SuperAdmin) -> MasterDataItem:
    if body.category not in MASTER_DATA_CATEGORIES:
        raise HTTPException(422, "Unknown category")
    if body.category in LOCKED:
        raise HTTPException(409, "This category's values are fixed because scoring depends on them")
    if (await db.execute(select(MasterDataItem.id).where(
            MasterDataItem.category == body.category, MasterDataItem.code == body.code))).first():
        raise HTTPException(409, "That code already exists in this category")
    last = (await db.execute(select(MasterDataItem.sort_order).where(MasterDataItem.category == body.category)
                             .order_by(MasterDataItem.sort_order.desc()).limit(1))).scalar() or 0
    item = MasterDataItem(category=body.category, code=body.code, label=body.label,
                          description=body.description, sort_order=last + 1)
    db.add(item)
    await db.commit()
    await enqueue_task("fanout_master_data", job_id="fanout_master_data")  # every company database keeps a copy
    return item


@router.put("/{item_id}", response_model=ItemOut)
async def edit_item(item_id: uuid.UUID, body: ItemEdit, db: ControlDB, _: SuperAdmin) -> MasterDataItem:
    item = await db.get(MasterDataItem, item_id)
    if item is None:
        raise HTTPException(404, "Not found")
    if item.category in LOCKED and not body.is_active:
        raise HTTPException(409, "These values can't be deactivated because scoring depends on them")
    item.label, item.description, item.is_active = body.label, body.description, body.is_active
    await db.commit()
    await enqueue_task("fanout_master_data", job_id="fanout_master_data")  # every company database keeps a copy
    return item


# ---------- organisational roles ----------


class RoleFields(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    abbreviation: str = Field(min_length=2, max_length=8, pattern=r"^[A-Z]+$")
    type: str
    reports_to: str | None = None
    description: str | None = None
    purpose: str | None = None
    accountabilities: str | None = None
    responsibilities: str | None = None
    decision_making_powers: str | None = None
    interfaces: str | None = None
    is_active: bool = True


class RoleOut(ORM, RoleFields):
    id: uuid.UUID
    code: str
    sort_order: int
    abbreviation: str  # no pattern check on output


ROLE_TEXT = ("reports_to", "description", "purpose", "accountabilities", "responsibilities",
             "decision_making_powers", "interfaces")


async def _check_role_body(db: ControlDB, body: RoleFields, role_id: uuid.UUID | None = None) -> None:
    if body.type not in ORG_ROLE_TYPES:
        raise HTTPException(422, "Type must be executive or operational")
    clash = (await db.execute(select(OrganisationalRole.id).where(
        OrganisationalRole.abbreviation == body.abbreviation, OrganisationalRole.id != role_id))).first()
    if clash:
        raise HTTPException(409, "Another role already uses that abbreviation")


def _apply_role(role: OrganisationalRole, body: RoleFields) -> None:
    role.name, role.abbreviation, role.type, role.is_active = body.name.strip(), body.abbreviation, body.type, body.is_active
    for f in ROLE_TEXT:
        setattr(role, f, (getattr(body, f) or "").strip() or None)


@router.get("/organisational-roles", response_model=list[RoleOut])
async def list_roles(db: ControlDB, _: CurrentUser) -> list[OrganisationalRole]:
    return list((await db.execute(select(OrganisationalRole).order_by(OrganisationalRole.sort_order))).scalars())


@router.post("/organisational-roles", response_model=RoleOut, status_code=201)
async def create_role(body: RoleFields, db: ControlDB, _: SuperAdmin) -> OrganisationalRole:
    await _check_role_body(db, body)
    last = (await db.execute(select(OrganisationalRole.sort_order).order_by(OrganisationalRole.sort_order.desc())
                             .limit(1))).scalar() or 0
    role = OrganisationalRole(code=body.abbreviation.lower(), sort_order=last + 1, name="", abbreviation="", type="")
    _apply_role(role, body)
    db.add(role)
    await db.commit()
    await enqueue_task("fanout_master_data", job_id="fanout_master_data")  # every company database keeps a copy
    return role


@router.put("/organisational-roles/{role_id}", response_model=RoleOut)
async def edit_role(role_id: uuid.UUID, body: RoleFields, db: ControlDB, _: SuperAdmin) -> OrganisationalRole:
    role = await db.get(OrganisationalRole, role_id)
    if role is None:
        raise HTTPException(404, "Not found")
    await _check_role_body(db, body, role_id)
    _apply_role(role, body)
    await db.commit()
    await enqueue_task("fanout_master_data", job_id="fanout_master_data")  # every company database keeps a copy
    return role
