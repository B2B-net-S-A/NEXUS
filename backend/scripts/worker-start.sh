#!/bin/bash
# Start kontenera `worker`. Rusza, gdy web odpowiada, więc nigdy nie widzi schematu
# w połowie zmian. Jeden proces uvicorna: dwa znaczyłyby dwa komplety pętli do lidera.
# → docs/claude/podstawy/web-i-worker-osobno.md
set -e

WEB_LIVE_URL="${NEXUS_WEB_LIVE_URL:-http://backend:8000/api/health/live}"
echo "=== Nexus ATS Worker: czekam na web (${WEB_LIVE_URL}) ==="
until curl -fsS --max-time 5 "${WEB_LIVE_URL}" >/dev/null 2>&1; do
    sleep 2
done
export DB_STATEMENT_TIMEOUT_MS=120000
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
