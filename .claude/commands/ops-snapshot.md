---
description: Snapshot nexus state (health + KPIs + queues) via /api/admin/snapshot
allowed-tools: Bash(source:*), Bash(curl:*), Bash(jq:*), Bash(git rev-parse:*), Bash(echo:*)
---

Pobierz pełny snapshot stanu **nexus** w jednym requeście (zamiast 5 round-tripów).

**Step 1 — fetch:**

```bash
source ~/.claude/secrets/dynaminds-tokens.env
curl -fsSL -H "X-Snapshot-Token: $NEXUS_SNAPSHOT_TOKEN" "https://api.nexus.dynaminds.pl/api/admin/snapshot" | jq .
```

**Step 2 — interpret response:**

- Render `health.status` z emoji: ✅ healthy / ⚠️ degraded / ❌ unhealthy
- `kpis` jako tabelka markdown (counts per kategoria)
- Compare `version` vs `git rev-parse --short HEAD` w bieżącym repo — flag drift jeśli nie matchuje
- Highlight `recent_errors_24h` jeśli >0 (sugeruj `mcp__sentry__list_issues` dla detali)
- Stalność: time since `generated_at` (np. "fresh: 12s ago" jeśli <30s, "cached: 28s ago" jeśli ≥30s, "stale: 5min ago" jeśli ≥1min)

**Error handling:**
- 404 → `/api/admin/snapshot` jeszcze nie zdeployowany (Phase 2 pending dla nexus). Powiedz to userowi.
- 401 → token problem. Verify: `echo "${NEXUS_SNAPSHOT_TOKEN}"` (powinno zwrócić wartość, nie pusty string). Jeśli pusto — `source ~/.claude/secrets/dynaminds-tokens.env` i retry.
- 503 → backend unhealthy. Sugeruj `/ops-health` dla szczegółów + `/ops-logs` jeśli database down.
