---
description: Tail docker logs from nexus server (docker logs <service> --tail N)
argument-hint: [service] [N=50]
allowed-tools: Bash(ssh:*)
---

Tail logi z **nexus** (server `91.99.199.112`).

User passed: `$ARGUMENTS`

Parse:
- 1st arg = service name (default `backend`)
- 2nd arg = tail line count (default 50)

```bash
ARGS="$ARGUMENTS"
SERVICE=$(echo "$ARGS" | awk '{print $1}')
SERVICE=${SERVICE:-backend}
TAIL=$(echo "$ARGS" | awk '{print $2}')
TAIL=${TAIL:-50}

ssh root@91.99.199.112 "docker logs $SERVICE --tail $TAIL --timestamps" 2>&1
```

**Common services (zależnie od repo):**
- backend — main app container
- postgres / nexus-db — Postgres (NEXUS)
- qdrant — vector DB (NEXUS)
- alloy — Grafana log shipper (Atlas, opcjonalnie NEXUS)
- scheduler — APScheduler standalone (Atlas only)
- coolify — Coolify itself (jeśli ops issue)
- coolify-proxy — Traefik (jeśli routing issue)

**Jeśli logi pokazują error:**
- ImportError / ModuleNotFoundError → build issue, sugeruj `/ops-deploy --force` (rebuild)
- DB connection refused → sprawdź postgres container `docker ps | grep postgres`
- 500/503 spam → sugeruj `mcp__sentry__list_issues` dla aggregated stacktrace

**Filtering tip:** dodaj `| grep ERROR` lub `| grep -E "WARN|ERROR"` w komendzie.
