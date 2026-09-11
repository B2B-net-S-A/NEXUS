"""0277 availability/allocation schema safety net for an orphaned Alembic bookmark.

Availability/allocation must be in place before ORM reads at login or startup
(`jobs.favorite_sourcing_paused`, `calendar_events.operational_owner_id` are
mapped columns). The exact idempotent migration is re-run in one transaction —
no second, divergent SQL copy. Moved out of an `entrypoint.sh` heredoc so the
lock handling below is exercised by tests, not only by a production start.
"""

import asyncio
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services.startup_locks import BOOT_LOCK_TIMEOUT, is_lock_timeout

# The same key as `recruitment_allocation.ALLOCATION_LOCK`: ownership commands
# take it before touching jobs, so the schema repair serialises with them.
ALLOCATION_LOCK = 734092771
MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0277_recruitment_allocation.py"
)

# What the ORM needs to start: the mapped columns, the tables and the enum
# value. Catalog reads only — none of them waits behind a table lock.
READY_SQL = """
SELECT
    (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND (table_name, column_name) IN (
              ('calendar_events', 'operational_owner_id'),
              ('jobs', 'favorite_sourcing_paused'),
              ('recruitment_priority_assignments', 'position')
          )
    ) = 3
    AND to_regclass('workforce_availability_state') IS NOT NULL
    AND to_regclass('recruitment_allocation_state') IS NOT NULL
    AND to_regclass('recruitment_allocation_requests') IS NOT NULL
    AND to_regclass('recruitment_allocation_events') IS NOT NULL
    AND EXISTS (
        SELECT 1
        FROM pg_enum AS label
        JOIN pg_type AS kind ON kind.oid = label.enumtypid
        WHERE kind.typname = 'notificationtype'
          AND label.enumlabel = 'recruitment_allocation_alert'
    )
"""


def ensure_allocation_schema(connection) -> None:
    spec = importlib.util.spec_from_file_location("allocation_schema", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()


async def main(engine=None) -> None:
    """Repair under a bounded lock wait; a timeout is fatal only if repair is needed.

    Fail-hard stays for an incomplete schema: an app whose ORM cannot read
    `jobs` must not start. But the migration takes ACCESS EXCLUSIVE on `jobs`,
    `calendar_events` and `recruitment_priority_assignments` on EVERY start.
    Unbounded, that hung the boot behind the nightly pg_dump and stalled every
    `jobs` reader of the still-serving container queued behind the request;
    with a limit alone it would crash-loop for the whole dump. A lock timeout
    on a schema that is already complete is therefore logged, not fatal.
    """
    owns_engine = engine is None
    if engine is None:
        from app.core.database import engine as app_engine

        engine = app_engine
    try:
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(f"SET LOCAL lock_timeout = '{BOOT_LOCK_TIMEOUT}'")
                )
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": ALLOCATION_LOCK},
                )
                await connection.run_sync(ensure_allocation_schema)
        except DBAPIError as exc:
            if not is_lock_timeout(exc):
                raise
            async with engine.connect() as connection:
                ready = await connection.scalar(text(READY_SQL))
            if not ready:
                raise
            print(
                "Availability/allocation schema already complete; repair skipped "
                "after a lock timeout (the next start retries)"
            )
            return
        print("Availability/allocation schema verified")
    finally:
        if owns_engine:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
