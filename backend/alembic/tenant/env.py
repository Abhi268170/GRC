"""Migrations of a company database: its users, runs and everything under them, plus copies
of the library tables and master data. The control database has its own tree in ../control.

The database to migrate is given by the caller (`python -m app.tenants migrate`), or on the
command line: `alembic -n tenant -x db=<database name> upgrade head`."""

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.db import url_for_database
from app.models import CONTROL_ONLY_TABLES, Base

config = context.config
if config.config_file_name is not None and not config.attributes.get("skip_logging"):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    return not (type_ == "table" and name in CONTROL_ONLY_TABLES)


def database_name() -> str:
    name = config.attributes.get("db_name") or context.get_x_argument(as_dictionary=True).get("db")
    if not name:
        raise SystemExit("Say which company database to migrate: alembic -n tenant -x db=<database name> ...")
    return name


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                      include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(url_for_database(database_name()))
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


asyncio.run(run_migrations_online())
