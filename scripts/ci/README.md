# Consumer CI command contract

Create executable, fail-closed scripts with these names before enabling workflows:

- `install` — deterministic install only (`npm ci`, frozen uv, etc.).
- `lint`, `typecheck`, `unit`, optional `integration`.
- `fresh-database` — empty DB → full migration → pgTAP/advisors or Alembic one-head checks.
- `authz-matrix` — anonymous, every role, unknown role and cross-user/cross-tenant negative tests.
- `dependency-audit` — block unexcepted HIGH/CRITICAL.
- `changed-coverage` — generate deterministic, complete LCOV at the repository-relative path passed as `coverage_lcov_path`. Include unimported in-scope source files with zero hits (`coverage.all`/`--cov=<package>`). The hash-locked central checker, not this script, enforces changed lines >=80% and the exact total ratchet.
- `combine-lcov` — normalize backend and frontend LCOV source paths to the repository root, then combine both reports for the central coverage checker.
- `docker-build` — build and tag `quality-gate:${GITHUB_SHA}` without production secrets.
- `migrate-staging`, `migrate-production-expand` — build the exact candidate
  image and invoke its fail-closed one-shot `migrate` mode with
  `MIGRATION_DATABASE_URL`; the URL is never expanded into process arguments.
- `snapshot-production` — use `SNAPSHOT_URL` and `SNAPSHOT_TOKEN`; trigger and verify the snapshot, then print exactly one non-secret reference matching `[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}` to stdout. Send operational logs to stderr.
- `e2e-staging` — target the application origin from `STAGING_BASE_URL`, never the readiness endpoint; consume synthetic role credentials from `STAGING_E2E_SECRETS_JSON` without printing it.
- `migration-head` — print exactly one migration-head identifier; `assert-rollback-allowed` — reject forbidden or below-floor `PREVIOUS_SHA`.

Scripts MUST use `set -euo pipefail` (or equivalent), bounded timeouts and redacted output. Replace template URLs/UUIDs before enabling release. Keep real values in repository variables or protected Environment secrets as appropriate.

Initialize `.standards/coverage-ratchet.json` only from a complete green run. The checked-in ratio MUST match current total coverage exactly; improvements raise it, and it cannot be lowered. A temporary `.security/exceptions/coverage.json` follows the central coverage-exception schema, requires independent approval and expires within 30 days.

## NEXUS exact-SHA release activation

`.github/workflows/deploy.yml` is fail-closed while
`NEXUS_RELEASE_PIPELINE_ENABLED` is not exactly `true`. Do not enable it until
`docs/ops/migration-reconciliation.md` is complete and independently reviewed.

Repository variables:

- `NEXUS_RELEASE_PIPELINE_ENABLED`
- `STAGING_COOLIFY_BASE_URL` and `PRODUCTION_COOLIFY_BASE_URL`
- `NEXUS_STAGING_APPLICATION_UUID` and `NEXUS_PRODUCTION_APPLICATION_UUID`
- `NEXUS_STAGING_BASE_URL` (the protected frontend application origin)
- `NEXUS_PRODUCTION_SNAPSHOT_URL` (a real verified PostgreSQL/Qdrant backup
  trigger, not `/api/admin/snapshot`)
- `ROLLBACK_FLOOR_SHA` (never an image containing the removed bootstrap-admin
  startup path)

Protected `staging` Environment secrets:

- `COOLIFY_TOKEN`, `MIGRATION_DATABASE_URL`
- `STAGING_E2E_SECRETS_JSON` containing only synthetic
  `E2E_USER_EMAIL`, `E2E_USER_PASSWORD`, `CF_ACCESS_CLIENT_ID`,
  `CF_ACCESS_CLIENT_SECRET` and optional `E2E_SESSION_COOKIE_PREFIX`

Protected `production` Environment secrets:

- `COOLIFY_TOKEN`, `MIGRATION_DATABASE_URL`, `SNAPSHOT_TOKEN`

The staging frontend exposes a same-origin `/api/health` facade. It forwards
the backend readiness response and fails with 503 when the backend cannot be
validated, so the locked release workflow never treats a frontend-only process
as ready.
