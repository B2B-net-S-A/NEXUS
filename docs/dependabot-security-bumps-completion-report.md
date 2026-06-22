[← back to docs](./)

# Dependabot Security Bumps — Completion Report

**Date:** 2026-06-22
**Branch:** `main` (commits `2007d31` backend, `71e1638` frontend)
**Scope:** Resolve the 28 open Dependabot advisories (2 critical, 7 high, 13 moderate, 6 low).

## Outcome

**27 of 28 advisories resolved** — all critical + all high cleared. 1 moderate
deferred (documented below).

| Severity | Open before | Resolved | Deferred |
|---|---|---|---|
| Critical | 2 | 2 | 0 |
| High | 7 | 7 | 0 |
| Moderate | 13 | 12 | 1 |
| Low | 6 | 6 | 0 |

## Backend — `backend/requirements.txt` (commit `2007d31`)

| Package | From → To | Advisories cleared |
|---|---|---|
| python-jose | 3.3.0 → 3.4.0 | #5 **CRITICAL** (ECDSA confusion), #4 (JWE DoS) |
| cryptography | 44.0.0 → 48.0.1 | #78 **HIGH** (OpenSSL wheel), #9 **HIGH** (subgroup attack), #10 low, #3 low |
| msal | 1.31.0 → 1.37.0 | enabler — old msal capped `cryptography<46`; 1.37 allows `<51` |
| python-multipart | 0.0.20 → 0.0.31 | #8 **HIGH** (arbitrary file write), #13 **HIGH** (DoS), #75 **HIGH** (semicolon DoS), #11 mod, #72/#73/#74 low |
| weasyprint | 63.0 → 68.0 | #7 **HIGH** (SSRF bypass) |
| jinja2 | 3.1.4 → 3.1.6 | #1, #2, #6 (sandbox breakouts) |
| bleach | 6.2.0 → 6.4.0 | #80 mod, #79 low (URI sanitization) |
| python-dotenv | 1.0.1 → 1.2.2 | #12 (symlink-follow in set_key) |

**pyHanko stays 0.34.1** — its only cryptography constraint is `>=43.0.3` (no
upper bound), verified compatible with 48.0.1 by the pip resolver. The stale
comment claiming a conflict was corrected.

## Frontend — `frontend/package.json` + `package-lock.json` (commit `71e1638`)

All frontend-flagged packages are **test/build tooling devDependencies** — none
ship in the Next.js production bundle.

| Package | From → To | Advisories cleared |
|---|---|---|
| vitest, @vitest/coverage-v8, @vitest/ui | 2.x → 3.2.6 | #70 **CRITICAL** (vitest UI arbitrary file read/exec) |
| vite (transitive via vitest) | 5.4.21 → 7.3.5 | #84 **HIGH** (fs.deny bypass), #85 mod, #24 mod |
| esbuild (transitive via vite) | 0.21.5 → 0.27.7 | #14 mod (dev-server requests) |
| postcss (override) | nested 8.4.31 → 8.5.15 | #29 mod (CSS stringify XSS) |
| uuid (override) | 9.0.1 → 11.1.1 | #58 mod (buffer bounds check in v3/v5/v6) |

## Deferred

- **#77 @opentelemetry/core (moderate)** — stays `1.30.1`. The fix is `2.8.0`, a
  major OTel `1.x → 2.x` bump. The whole OpenTelemetry ecosystem (`@sentry/node`,
  all `@opentelemetry/instrumentation-*`) pins `^1.x`, so it can only move via a
  `@sentry/nextjs` v10 major upgrade — out of scope for a safe security patch.
  Vuln is server-side W3C Baggage propagation memory growth; low practical risk.
  **Follow-up:** bundle with a future `@sentry/nextjs` 9 → 10 upgrade.

## Verification (pre-push, in Docker matching prod images)

**Backend** (`python:3.12-slim` + Postgres 16 sidecar):
- pip resolver: clean full resolution, no conflicts.
- App boots end-to-end: `alembic upgrade head` + FastAPI lifespan + 14 background
  tasks + DB connection all OK.
- `pytest` dependency-sensitive subset: **78 passed** — covers weasyprint (autenti
  PDF renderer), cryptography (m365 encryption), python-jose (JWT auth, password
  reset, health, autenti webhook verify), msal (auth microsoft), python-multipart
  (api integration).
- Confirmed versions: crypto 48.0.1, weasy 68.0, msal 1.37.0, bleach 6.4.0, jinja2 3.1.6.

**Frontend** (`node:20-alpine`, `--legacy-peer-deps`):
- `tsc --noEmit`: clean.
- `vitest run`: **188 tests passed** under vitest 3.2.6 / vite 7.
- `next build`: succeeds (uuid 11 override does not break `@sentry/webpack-plugin`).

## Deploy

- Pushed `main` → CI (gitleaks + lint + typecheck + tests + build) + Coolify
  auto-deploy → `/api/health` smoke-test (GIT_SHA prefix-match `71e1638`).
