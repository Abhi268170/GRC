"""Copies from the control database into a company database.

A company database holds its own copy of the library rows its runs use, so run data keeps
real foreign keys and joins. Published versions never change, so a copy stays correct.
Rows keep their ids: copying twice does nothing, and a second run on the same assessment
version reuses the first copy. Master data and organisational roles are mirrored in full.
See TENANT_DATABASE_PLAN.md §3 and §4."""

import uuid

from sqlalchemy import Table, select, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AppUser,
    Assessment,
    AssessmentRun,
    AssessmentVersion,
    AssessmentVersionControl,
    AssessmentVersionDomain,
    Control,
    ControlVersion,
    ControlVersionClassification,
    Domain,
    DomainVersion,
    Framework,
    FrameworkClause,
    FrameworkVersion,
    MasterDataItem,
    Notification,
    OrganisationalRole,
    Question,
    QuestionRequirement,
    Requirement,
    RequirementClauseMap,
    RequirementVersion,
)

MAX_PARAMS = 30000  # asyncpg allows 32767 bind parameters per statement

# Columns that point at rows a company database doesn't have (the super admin, control imports).
CLEARED = {"published_by", "created_by", "import_id"}


def _chunks(table: Table, rows: list[dict]) -> list[list[dict]]:
    size = max(1, MAX_PARAMS // len(table.c))
    return [rows[i:i + size] for i in range(0, len(rows), size)]


async def _rows(control: AsyncSession, model, where, order_by=None) -> list[dict]:
    query = select(model.__table__).where(where)
    if order_by is not None:
        query = query.order_by(order_by)
    return [dict(r) for r in (await control.execute(query)).mappings()]


async def _insert_missing(tenant: AsyncSession, model, rows: list[dict]) -> None:
    table = model.__table__
    for row in rows:
        for column in CLEARED & row.keys():
            row[column] = None
    for chunk in _chunks(table, rows):
        await tenant.execute(insert(table).values(chunk).on_conflict_do_nothing())


async def sync_master_data(control: AsyncSession, tenant: AsyncSession) -> None:
    """Make the company database's master data and organisational roles match the control database.
    Values are never deleted (only switched off), so this only adds and updates."""
    for model in (MasterDataItem, OrganisationalRole):
        table = model.__table__
        for chunk in _chunks(table, await _rows(control, model, true())):
            stmt = insert(table).values(chunk)
            await tenant.execute(stmt.on_conflict_do_update(
                index_elements=[table.c.id],
                set_={c.name: stmt.excluded[c.name] for c in table.c if not c.primary_key},
            ))


async def _sync_deprecated(control: AsyncSession, tenant: AsyncSession, model, parent: str, parent_ids: set[uuid.UUID]) -> None:
    """Copies made earlier may still say "published" for versions the control database has since
    deprecated. Bring them up to date, so a newer published version of the same thing can be copied
    (only one published version per parent is allowed)."""
    if not parent_ids:
        return
    column = getattr(model, parent)
    stale = (await tenant.execute(select(model.id).where(column.in_(parent_ids), model.status == "published"))).scalars().all()
    if not stale:
        return
    deprecated = (await control.execute(select(model.id).where(model.id.in_(stale), model.status == "deprecated"))).scalars().all()
    if deprecated:
        await tenant.execute(update(model).where(model.id.in_(deprecated)).values(status="deprecated"))


async def copy_assessment_version(control: AsyncSession, tenant: AsyncSession, version_id: uuid.UUID) -> None:
    """Copy one published assessment version, and everything it points to, into a company database."""
    await sync_master_data(control, tenant)

    AVC, RV, RCM, FC, Q = AssessmentVersionControl, RequirementVersion, RequirementClauseMap, FrameworkClause, Question
    cv_ids = select(AVC.control_version_id).where(AVC.assessment_version_id == version_id)
    rv_ids = select(RV.id).where(RV.control_version_id.in_(cv_ids))
    fv_ids = select(FC.framework_version_id).where(
        FC.id.in_(select(RCM.framework_clause_id).where(RCM.requirement_version_id.in_(rv_ids))))

    versions = await _rows(control, AssessmentVersion, AssessmentVersion.id == version_id)
    version_domains = await _rows(control, AssessmentVersionDomain, AssessmentVersionDomain.assessment_version_id == version_id)
    control_versions = await _rows(control, ControlVersion, ControlVersion.id.in_(cv_ids))
    domain_versions = await _rows(control, DomainVersion, DomainVersion.id.in_([d["domain_version_id"] for d in version_domains]))
    framework_versions = await _rows(control, FrameworkVersion, FrameworkVersion.id.in_(fv_ids))
    assessment_ids = {v["assessment_id"] for v in versions}
    control_ids = {c["control_id"] for c in control_versions}
    domain_ids = {d["domain_id"] for d in domain_versions} | {c["domain_id"] for c in control_versions}
    framework_ids = {f["framework_id"] for f in framework_versions}

    for model, parent, parent_ids in (
        (AssessmentVersion, "assessment_id", assessment_ids), (ControlVersion, "control_id", control_ids),
        (DomainVersion, "domain_id", domain_ids), (FrameworkVersion, "framework_id", framework_ids),
    ):
        await _sync_deprecated(control, tenant, model, parent, parent_ids)

    # Parents before children, so every foreign key finds its row.
    copies = [
        (Framework, await _rows(control, Framework, Framework.id.in_(framework_ids))),
        (FrameworkVersion, framework_versions),
        # All clauses of each framework version, parents first (level 0, then 1, ...).
        (FrameworkClause, await _rows(control, FC, FC.framework_version_id.in_(fv_ids), FC.level)),
        (Domain, await _rows(control, Domain, Domain.id.in_(domain_ids))),
        (DomainVersion, domain_versions),
        (Control, await _rows(control, Control, Control.id.in_(control_ids))),
        (ControlVersion, control_versions),
        (ControlVersionClassification,
         await _rows(control, ControlVersionClassification, ControlVersionClassification.control_version_id.in_(cv_ids))),
        (Requirement, await _rows(control, Requirement, Requirement.id.in_(
            select(RV.requirement_id).where(RV.control_version_id.in_(cv_ids))))),
        (RequirementVersion, await _rows(control, RV, RV.control_version_id.in_(cv_ids))),
        (RequirementClauseMap, await _rows(control, RCM, RCM.requirement_version_id.in_(rv_ids))),
        (Assessment, await _rows(control, Assessment, Assessment.id.in_(assessment_ids))),
        (AssessmentVersion, versions),
        (AssessmentVersionDomain, version_domains),
        (AssessmentVersionControl, await _rows(control, AVC, AVC.assessment_version_id == version_id)),
        (Question, await _rows(control, Q, Q.assessment_version_id == version_id)),
        (QuestionRequirement, await _rows(control, QuestionRequirement, QuestionRequirement.question_id.in_(
            select(Q.id).where(Q.assessment_version_id == version_id)))),
    ]
    for model, rows in copies:
        await _insert_missing(tenant, model, rows)


async def deprecate_assessment_version(tenant: AsyncSession, version_id: uuid.UUID, payload: dict) -> int:
    """A newer version was published: mark this company's copy of the old one as deprecated and
    notify the people who started a run on it, and the company's admins. Returns the number of notices."""
    version = await tenant.get(AssessmentVersion, version_id)
    if version is None:
        return 0  # this company never ran that version
    version.status = "deprecated"
    starters = set((await tenant.execute(
        select(AssessmentRun.started_by).where(AssessmentRun.assessment_version_id == version_id))).scalars())
    if not starters:
        return 0
    admins = (await tenant.execute(select(AppUser.id).where(AppUser.platform_role == "tenant_admin"))).scalars()
    recipients = starters | set(admins)
    for user_id in recipients:
        tenant.add(Notification(user_id=user_id, type="assessment_deprecated", payload=payload))
    return len(recipients)
