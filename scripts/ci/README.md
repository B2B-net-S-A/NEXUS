# Consumer CI command contract

Create executable, fail-closed scripts with these names before enabling workflows:

- `install` — deterministic install only (`npm ci`, frozen uv, etc.).
- `lint`, `typecheck`, `unit`, optional `integration`.
- `fresh-database` — empty DB → full migration → pgTAP/advisors or Alembic one-head checks.
- `authz-matrix` — anonymous, every role, unknown role and cross-user/cross-tenant negative tests.
- `dependency-audit` — block unexcepted HIGH/CRITICAL.
- `changed-coverage` — changed lines >=80%; total cannot decrease.
- `docker-build` — build and tag `quality-gate:${GITHUB_SHA}` without production secrets.
- `migrate-staging`, `migrate-production-expand` — build the exact candidate
  image and invoke its fail-closed one-shot `migrate` mode with
  `MIGRATION_DATABASE_URL`; the URL is never expanded into process arguments.
- `snapshot-production` — use `SNAPSHOT_URL` and `SNAPSHOT_TOKEN`; trigger and verify the snapshot, then print exactly one non-secret reference matching `[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}` to stdout. Send operational logs to stderr.
- `e2e-staging` — target the application origin from `STAGING_BASE_URL`, never the readiness endpoint; consume synthetic role credentials from `STAGING_E2E_SECRETS_JSON` without printing it.
- `migration-head` — print exactly one migration-head identifier; `assert-rollback-allowed` — reject forbidden or below-floor `PREVIOUS_SHA`.

Scripts MUST use `set -euo pipefail` (or equivalent), bounded timeouts and redacted output. Replace template URLs/UUIDs before enabling release. Keep real values in repository variables or protected Environment secrets as appropriate.
