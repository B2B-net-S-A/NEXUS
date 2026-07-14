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
