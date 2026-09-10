"""0282 signature-confirmation policy safety net for an orphaned Alembic bookmark.

Reuses the migration only when the schema/policy is missing; a normal restart
must never recreate user overrides or increment the policy revision. Moved out
of an `entrypoint.sh` heredoc so its lock handling is exercised by tests, not
only by a production start (the same move as `allocation_schema_bootstrap`).

SOFT only on a lock timeout. The repair is not a precondition of the start:
without the policy the app runs, only the separate permission to confirm a
signature is missing, and the next start retries. Unbounded, the 0282 DDL
waited for ACCESS EXCLUSIVE behind the nightly pg_dump and the start hung
without end. Every OTHER failure — a broken migration, a missing table, a bad
connection — still stops the start, as it did before 09.2026: the heredoc that
swallowed every exception would have started the container silently without
the policy and reported nothing.
"""

import asyncio
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.services.startup_locks import BOOT_LOCK_TIMEOUT, is_lock_timeout

POLICY_LOCK = 734092782
MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0282_b2b_signature_permission.py"
)

# Both CHECK constraints accept the action and the role matrix carries it.
READY_SQL = """
SELECT (
    SELECT count(*) FROM pg_constraint
    WHERE conname IN ('ck_rbac_role_action_permissions_action',
                      'ck_rbac_user_action_overrides_action')
      AND pg_get_constraintdef(oid) LIKE '%b2b_signature_confirmation%'
) = 2 AND EXISTS (
    SELECT 1 FROM rbac_role_action_permissions
    WHERE action = 'b2b_signature_confirmation'
)
"""


def ensure_signature_policy(connection) -> None:
    spec = importlib.util.spec_from_file_location("signature_policy_schema", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()


async def main(engine=None) -> None:
    """Verify (and if needed repair) the policy; skip only after a lock timeout."""
    owns_engine = engine is None
    if engine is None:
        from app.core.database import engine as app_engine

        engine = app_engine
    try:
        try:
            async with engine.begin() as connection:
                # Before the advisory lock: the wait for it is bounded too.
                await connection.execute(
                    text(f"SET LOCAL lock_timeout = '{BOOT_LOCK_TIMEOUT}'")
                )
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": POLICY_LOCK}
                )
                await connection.execute(
                    text("SELECT id FROM rbac_policy_state WHERE id = 1 FOR UPDATE")
                )
                ready = await connection.scalar(text(READY_SQL))
                if not ready:
                    await connection.run_sync(ensure_signature_policy)
        except Exception as exc:
            if not is_lock_timeout(exc):
                raise
            print(
                "Signature confirmation policy skipped after a lock timeout "
                f"(the next start retries): {type(exc).__name__}"
            )
            return
        print("Signature confirmation policy verified")
    finally:
        if owns_engine:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
