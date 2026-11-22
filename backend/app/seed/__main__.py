"""Seed entry point. Idempotent: each section only inserts what is missing, so it is
safe to run on every start (the migrate service does). Seeds the control database, then
brings every company database's copy of the master data up to date."""

import asyncio
import json
import uuid
from pathlib import Path
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import ControlSession, dispose_all
from app.core.security import hash_password
from app.models import (
    AppUser,
    Domain,
    DomainVersion,
    Framework,
    FrameworkClause,
    FrameworkVersion,
    LoginDirectory,
    MasterDataItem,
    OrganisationalRole,
)
from app.seed.frameworks import FRAMEWORKS
from app.seed.library import DOMAINS
from app.seed.master_data import MASTER_DATA
from app.services import tenants

ROLES_FILE = Path(__file__).with_name("organisational_roles.json")
ROLE_FIELDS = ("name", "abbreviation", "type", "reports_to", "description", "purpose", "accountabilities",
               "responsibilities", "decision_making_powers", "interfaces", "sort_order")


def now() -> datetime:
    return datetime.now(UTC)


async def seed_master_data(db: AsyncSession) -> None:
    existing = {(c, k) for c, k in (await db.execute(select(MasterDataItem.category, MasterDataItem.code)))}
    added = 0
    for category, items in MASTER_DATA.items():
        for order, (code, label, value, description) in enumerate(items):
            if (category, code) in existing:
                continue
            db.add(MasterDataItem(category=category, code=code, label=label, numeric_value=value,
                                  description=description, sort_order=order))
            added += 1
    print(f"[seed] master data: {added} added")


async def seed_super_admin(db: AsyncSession) -> uuid.UUID:
    s = get_settings()
    user = (await db.execute(select(AppUser).where(AppUser.email == s.super_admin_email))).scalar_one_or_none()
    if user is None:
        user = AppUser(email=s.super_admin_email, password_hash=hash_password(s.super_admin_password),
                       full_name=s.super_admin_name, platform_role="super_admin")
        db.add(user)
        await db.flush()
        print(f"[seed] super admin created: {s.super_admin_email}")
    # The login directory says which database an email signs in to (no tenant = this one).
    if await db.get(LoginDirectory, s.super_admin_email.lower()) is None:
        db.add(LoginDirectory(email=s.super_admin_email.lower(), tenant_id=None))
    return user.id


async def seed_frameworks(db: AsyncSession, admin_id: uuid.UUID) -> None:
    """Creates missing frameworks, and adds missing clauses to the published version of existing ones
    (matched by clause ref). Existing clauses keep their id and title; only their place in the tree
    is brought in line with the list."""
    for fw in FRAMEWORKS:
        parent_of = {ref: parent for ref, _, parent, _ in fw["clauses"]}
        framework = (await db.execute(select(Framework).where(Framework.code == fw["code"]))).scalar_one_or_none()
        if framework is None:
            framework = Framework(code=fw["code"], name=fw["name"], publisher=fw["publisher"])
            db.add(framework)
            await db.flush()
            version = FrameworkVersion(framework_id=framework.id, version=1, version_label=fw["version_label"],
                                       status="published", published_at=now(), published_by=admin_id)
            db.add(version)
            await db.flush()
        else:
            framework.name, framework.publisher = fw["name"], fw["publisher"]
            version = (await db.execute(select(FrameworkVersion).where(
                FrameworkVersion.framework_id == framework.id, FrameworkVersion.status == "published",
                FrameworkVersion.version_label == fw["version_label"]))).scalar_one_or_none()
            if version is None:
                print(f"[seed] framework {fw['code']}: no published version {fw['version_label']}, left as it is")
                continue
        existing = {c.ref: c for c in (await db.execute(
            select(FrameworkClause).where(FrameworkClause.framework_version_id == version.id))).scalars()}
        ids = {ref: c.id for ref, c in existing.items()}
        added = 0
        for order, (ref, title, parent, assessable) in enumerate(fw["clauses"]):
            parent_id, level = ids.get(parent) if parent else None, clause_level(parent_of, ref)
            clause = existing.get(ref)
            if clause is None:
                clause = FrameworkClause(framework_version_id=version.id, parent_id=parent_id, ref=ref, title=title,
                                         level=level, sort_order=order, is_assessable=assessable)
                db.add(clause)
                await db.flush()
                ids[ref] = clause.id
                added += 1
            else:
                clause.parent_id, clause.level, clause.sort_order = parent_id, level, order
        print(f"[seed] framework {fw['code']} {fw['version_label']}: {added} clauses added ({len(fw['clauses'])} in the list)")


def clause_level(parent_of: dict[str, str | None], ref: str) -> int:
    level, parent = 0, parent_of[ref]
    while parent is not None:
        level, parent = level + 1, parent_of[parent]
    return level


async def seed_organisational_roles(db: AsyncSession) -> None:
    """Loads organisational_roles.json. Adds missing roles; existing ones are left as edited in the app."""
    existing = set((await db.execute(select(OrganisationalRole.code))).scalars())
    added = 0
    for row in json.loads(ROLES_FILE.read_text()):
        if row["code"] in existing:
            continue
        db.add(OrganisationalRole(code=row["code"], **{k: row.get(k) for k in ROLE_FIELDS}))
        added += 1
    print(f"[seed] organisational roles: {added} added")


async def seed_domains(db: AsyncSession, admin_id: uuid.UUID) -> None:
    added = 0
    for abbreviation, name, *rest in DOMAINS:
        description = rest[0] if rest else None
        if (await db.execute(select(Domain.id).where(Domain.abbreviation == abbreviation))).first():
            continue
        domain = Domain(abbreviation=abbreviation)
        db.add(domain)
        await db.flush()
        db.add(DomainVersion(domain_id=domain.id, version=1, status="published", name=name, description=description,
                             published_at=now(), published_by=admin_id))
        added += 1
    print(f"[seed] domains: {added} added")


async def main() -> None:
    async with ControlSession() as db, db.begin():
        await seed_master_data(db)
        admin_id = await seed_super_admin(db)
        await seed_organisational_roles(db)
        await seed_frameworks(db, admin_id)
        await seed_domains(db, admin_id)
    synced = await tenants.sync_master_data_everywhere()
    print(f"[seed] master data synced to {synced} company database(s)")
    await dispose_all()
    print("[seed] done")


if __name__ == "__main__":
    asyncio.run(main())
