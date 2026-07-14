# NEXUS migration reconciliation runbook

This runbook is mandatory before enabling the exact-SHA production release.
Application startup is schema-read-only; only the one-shot `migrate` command
may execute DDL.

## Staging and empty-database proof

1. Build the exact candidate SHA.
2. Start an empty PostgreSQL 16 instance with synthetic data only.
3. Run the candidate image with command `migrate`. The executable command is
   exactly `alembic -c alembic/alembic.ini upgrade head`.
4. Require one repository head and one matching row in `alembic_version` via
   `python -m scripts.assert_migration_head`.
5. Run `alembic -c alembic/alembic.ini check`. Its documented contract checks
   that every ORM-managed table and column exists; raw-SQL reporting tables and
   hand-tuned indexes are intentionally not removal candidates.
6. Start the backend and require readiness plus the compatibility deep-health
   probe. A failed migration/head gate must exit before Uvicorn serves.

## Production reconciliation prerequisite

Do not apply revision `0161_reconcile_startup_schema` directly to the live
database first. It replaces years of tolerant startup repairs and contains
PostgreSQL enum operations that use Alembic's autocommit block.

1. Take and verify a PostgreSQL snapshot/backup; record its non-secret
   reference in the release manifest.
2. Restore the current production database into an isolated, encrypted clone
   with no application or public network access.
3. Preserve evidence from the clone: current `alembic_version` row(s), schema
   dump hash, database size, migration runtime and failing statement if any.
4. Run the exact candidate image's one-shot `migrate` command against the
   clone. Never use `alembic stamp`, `upgrade heads`, manual DDL, or the web
   entrypoint to bypass a failure.
5. Require the single expected head, `alembic check`, critical role/API tests,
   and a schema-only dump diff reviewed by a second engineer.
6. Destroy the clone after the review and retention window.
7. Only then may the protected production workflow take a new snapshot and run
   the same candidate migration before switching application traffic.

Migration failure stops the release. Revision 0161 is forward-only: recovery
is a verified snapshot restore or a new corrective forward migration, never a
best-effort downgrade. The previous image remains an allowed rollback target
only when its schema compatibility is above the recorded rollback floor and it
does not contain the removed bootstrap-administrator path.
