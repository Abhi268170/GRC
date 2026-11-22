"""Company database commands.

    python -m app.tenants migrate    upgrade the control database, then every company database
    python -m app.tenants list       list companies and their databases"""

import asyncio
import logging
import sys

from app.core.db import ControlSession, dispose_all
from app.services import tenants


async def _migrate() -> int:
    try:
        failed = await tenants.migrate_all()
    finally:
        await dispose_all()
    for name in failed:
        print(f"[tenants] FAILED, now offline until fixed: {name}")
    # The control database is upgraded and the other companies work: let the platform start.
    return 0


async def _list() -> int:
    from sqlalchemy import select

    from app.models import Tenant

    try:
        async with ControlSession() as control:
            for t in (await control.execute(select(Tenant).order_by(Tenant.created_at))).scalars():
                print(f"{t.id}  {t.status:<12}  {t.db_name}  {t.name}")
    finally:
        await dispose_all()
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    commands = {"migrate": _migrate, "list": _list}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(__doc__)
    sys.exit(asyncio.run(commands[sys.argv[1]]()))


if __name__ == "__main__":
    main()
