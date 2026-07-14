import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base

# Import all models so Alembic picks them up
import app.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_schema_contract_object(
    object_, name: str | None, type_: str, reflected: bool, compare_to
) -> bool:
    """Make ``alembic check`` enforce the runtime compatibility contract.

    The historical database contains intentionally unmanaged raw-SQL reporting
    tables and many hand-tuned indexes that are not represented in SQLAlchemy
    metadata. Treating those as removal candidates produces thousands of false
    positives and can encourage destructive migrations. The deployment risk we
    must block is the inverse: an ORM table or column used by the application
    missing from the migrated database. Existing objects are therefore ignored
    after their presence is established; metadata-only tables/columns remain
    visible to autogenerate and make ``alembic check`` fail.
    """

    del object_, name
    if type_ == "table":
        return not (reflected and compare_to is None)
    if type_ == "column":
        return compare_to is None and not reflected
    return False


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_schema_contract_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_schema_contract_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
