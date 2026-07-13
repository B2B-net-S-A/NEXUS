# Shared engineering baseline / Wspólny standard

- Follow the immutable engineering standard version recorded in `.standards/standards.lock.json`.
- Changes to auth, roles, RLS, storage, sessions, secrets, migrations, deployment or health are security-sensitive and require negative tests.
- Use fresh forward-only migrations; never mutate schema or bootstrap users at application startup.
- Authorization fails closed. Unknown/missing roles, missing membership and dependency failures never grant a default role.
- Client inputs are strict. Privileged clients and service credentials stay in a server-only layer.
- Production deploys only the exact 40-character SHA that passed required CI and staging.
- Never print or commit secrets, production data, private signed URLs or raw evidence.
- Preserve existing user changes. Perform security work in a fresh branch/worktree from current `origin/main`.
- Application-specific deviations belong under `Local deviations` below. A deviation cannot weaken a MUST without a valid temporary exception.

## Local deviations / Lokalne wyjątki

- Backend: FastAPI, SQLAlchemy async and Alembic on Python 3.12; runtime port `8000`.
- Frontend: Next.js on Node 20; package manager npm. Frontend runtime port is `3000`.
- Data services: PostgreSQL and Qdrant. Both are required production components; readiness must not report `healthy` when either required component is unavailable.
- Docker liveness is `GET /api/livez`; release readiness is `GET /api/health`.
- `GET /api/health/deep` is a one-release compatibility alias while its ORM schema probes are folded into the migration gate.
- Existing startup DDL and `Base.metadata.create_all` are unresolved migration debt, not an approved deviation. Exact-SHA release v2 remains disabled until they are removed and a one-head Alembic replay is proven from an empty database.
- Production rollback must never select an image containing the removed bootstrap-administrator path.
- The legacy branch-based deployment workflow is intentionally blocked. It must not be re-enabled instead of the staged exact-SHA release path.
- When exact-SHA release is enabled, staging and production use explicit, independent Coolify control-plane URLs. The legacy production-only `COOLIFY_URL` must not be reused as an implicit shared endpoint.
- Release-gate work must include NEXUS P0 PR #684 (or its equivalent) before merge; otherwise the old broad Gitleaks exclusions for `backend/scripts` and `entrypoint.sh` remain in force.
