"""Action items and risk register (tenant-wide, across runs)."""

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.runs import ActionOut, RiskOut, action_out, risk_out
from app.core.auth import TenantDB, TenantMember
from app.models import ActionItem, AppUser, AssessmentRun, Risk
from app.services import runs as svc

router = APIRouter(tags=["registers"])


class ActionRow(ActionOut):
    run_id: uuid.UUID | None
    run_title: str | None


class RiskRow(RiskOut):
    run_id: uuid.UUID | None
    run_title: str | None


class ActionEdit(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=8000)
    priority: str = Field(pattern="^(low|medium|high|critical)$")
    status: str = Field(pattern="^(suggested|open|in_progress|done|dismissed)$")
    owner_id: uuid.UUID | None = None
    due_date: date | None = None


class RiskEdit(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=8000)
    category: str | None = Field(default=None, max_length=64)
    likelihood: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    treatment: str | None = Field(default=None, pattern="^(mitigate|accept|transfer|avoid)$")
    status: str = Field(pattern="^(suggested|open|mitigating|accepted|closed|dismissed)$")
    owner_id: uuid.UUID | None = None


async def _scopes(db: TenantDB, run_ids: set[uuid.UUID]) -> dict:
    out = {}
    for rid in run_ids:
        run = await db.get(AssessmentRun, rid)
        out[rid] = (run, await svc.load_run_scope(db, run.assessment_version_id))
    return out


async def _check_owner(db: TenantDB, me: AppUser, owner_id: uuid.UUID | None) -> None:
    if owner_id:
        owner = await db.get(AppUser, owner_id)
        if owner is None:
            raise HTTPException(422, "Unknown team member")


async def _editable(db: TenantDB, me: AppUser, item, new_status: str) -> None:
    """Who may change an action item or risk: a tenant admin, its owner, or a reviewer of the run it
    came from. A suggestion under review belongs to the run's reviewers only, and nothing goes back
    to being a suggestion once it has left that state."""
    if item is None:
        raise HTTPException(404, "Not found")
    run = await db.get(AssessmentRun, item.run_id) if item.run_id else None
    reviewer = me.platform_role == "tenant_admin" or (run is not None and svc.can_review(me, run))
    if item.status == "suggested":
        if not reviewer:
            raise HTTPException(403, "Only reviewers can change suggestions under review")
    elif not (reviewer or item.owner_id == me.id):
        raise HTTPException(403, "Only an admin, the owner, or the assessment's reviewer can change this")
    if new_status == "suggested" and item.status != "suggested":
        raise HTTPException(422, "An item can't go back to being a suggestion")


@router.get("/action-items", response_model=list[ActionRow])
async def list_actions(db: TenantDB, me: TenantMember) -> list[ActionRow]:
    items = (await db.execute(select(ActionItem).where(ActionItem.status != "suggested")
                              .order_by(ActionItem.created_at.desc()))).scalars().all()
    scopes = await _scopes(db, {i.run_id for i in items if i.run_id})
    rows = []
    for i in items:
        run, scope = scopes.get(i.run_id, (None, None))
        rows.append(ActionRow(**(await action_out(db, scope, i)).model_dump(), run_id=i.run_id, run_title=run.title if run else None))
    return rows


@router.put("/action-items/{item_id}", response_model=ActionOut)
async def edit_action(item_id: uuid.UUID, body: ActionEdit, db: TenantDB, me: TenantMember) -> ActionOut:
    item = await db.get(ActionItem, item_id)
    await _editable(db, me, item, body.status)
    await _check_owner(db, me, body.owner_id)
    for k, v in body.model_dump().items():
        setattr(item, k, v)
    await db.commit()
    scope = (await _scopes(db, {item.run_id}))[item.run_id][1] if item.run_id else None
    return await action_out(db, scope, item)


@router.get("/risks", response_model=list[RiskRow])
async def list_risks(db: TenantDB, me: TenantMember) -> list[RiskRow]:
    items = (await db.execute(select(Risk).where(Risk.status != "suggested")
                              .order_by((Risk.likelihood * Risk.impact).desc()))).scalars().all()
    scopes = await _scopes(db, {i.run_id for i in items if i.run_id})
    rows = []
    for i in items:
        run, scope = scopes.get(i.run_id, (None, None))
        rows.append(RiskRow(**(await risk_out(db, scope, i)).model_dump(), run_id=i.run_id, run_title=run.title if run else None))
    return rows


@router.put("/risks/{risk_id}", response_model=RiskOut)
async def edit_risk(risk_id: uuid.UUID, body: RiskEdit, db: TenantDB, me: TenantMember) -> RiskOut:
    risk = await db.get(Risk, risk_id)
    await _editable(db, me, risk, body.status)
    await _check_owner(db, me, body.owner_id)
    for k, v in body.model_dump().items():
        setattr(risk, k, v)
    await db.commit()
    scope = (await _scopes(db, {risk.run_id}))[risk.run_id][1] if risk.run_id else None
    return await risk_out(db, scope, risk)
