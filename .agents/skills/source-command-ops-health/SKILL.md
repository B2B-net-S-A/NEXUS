---
name: "source-command-ops-health"
description: "Quick health check for nexus via /api/health"
---

# source-command-ops-health

Use this skill when the user asks to run the migrated source command `ops-health`.

## Command Template

Szybki health check **nexus** — wersja, status DB, deploy time.

```bash
SHORT_SHA=$(git rev-parse --short=7 HEAD 2>/dev/null || echo "<not-in-git>")
echo "Local HEAD: $SHORT_SHA"
curl -fsSL "https://api.nexus.dynaminds.pl/api/health" | jq .
```

**Interpret:**
- `status` — healthy/degraded/unhealthy z emoji
- `checks` — wszystkie sub-checks (database, m365, ...) z ✅/❌
- Compare `version` startswith "$SHORT_SHA" — jeśli nie matchuje:
  - Deployed jest starsza niż local main (pending deploy)
  - LUB inna branch zdeployowana (sprawdź `gh run list --workflow Deploy --branch main --limit 1`)
- `deployedAt` — relative time ("8h ago", "wczoraj 14:00")

**Jeśli non-200:**
- 503 → status="unhealthy", at least one check failed. Sugeruj `/ops-logs` dla backend service.
- 502 → backend container down lub unstable. Sugeruj `/ops-logs` + Coolify panel check.
- timeout → DNS/network problem albo Cloudflare incident. Test: `curl -I https://https://api.nexus.dynaminds.pl` (gołe headers, sprawdź czy CF zwraca anything).
