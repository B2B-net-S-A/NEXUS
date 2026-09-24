#!/usr/bin/env bash
# Monitor produkcji na czas testu obciążeniowego (tylko odczyt).
#
# Co INTERVAL sekund dopisuje do CSV: czas odpowiedzi /api/health/live z zewnątrz,
# status /api/health, nazwę kontenera backendu (zmiana = deploy w trakcie testu),
# CPU/RAM kontenerów oraz stan połączeń backendu w pg_stat_activity.
#
#   qa/load/prod_monitor.sh .qa/loadrun/monitor.csv   # Ctrl+C kończy
set -uo pipefail

OUT="${1:?podaj plik CSV}"
INTERVAL="${INTERVAL:-15}"
API="${NEXUS_API_URL:-https://api.nexus.dynaminds.pl}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/nexus_prod_root_ed25519}"
HOST="${PROD_HOST:-root@91.99.199.112}"

# Jedno wywołanie SSH na próbkę. Zapytanie SQL jest w transakcji tylko do odczytu.
read -r -d '' REMOTE <<'EOF'
b=$(docker ps --format '{{.Names}}' | grep '^backend-ocgkw' | head -1)
p=$(docker ps --format '{{.Names}}' | grep '^postgres-ocgkw' | head -1)
f=$(docker ps --format '{{.Names}}' | grep '^frontend-ocgkw' | head -1)
s=$(docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' "$b" "$p" "$f" \
    | awk '{sub(/-ocgkw.*/,"",$1); printf "%s:%s:%s;", $1, $2, $3}')
q=$(docker exec -i "$p" psql -U nexus -d nexus -At -F ' ' -c "BEGIN READ ONLY;
SELECT count(*) FILTER (WHERE state='active'), count(*) FILTER (WHERE state='idle in transaction'),
       count(*), coalesce(round(max(extract(epoch FROM now()-query_start)) FILTER (WHERE state='active'))::int,0)
FROM pg_stat_activity WHERE application_name='nexus-backend'; COMMIT;" | sed -n 2p)
l=$(cut -d' ' -f1 /proc/loadavg)
echo "$b|$s|$q|$l"
EOF

[ -s "$OUT" ] || echo "ts,live_code,live_ms,health_status,backend_container,containers,pg_active,pg_idle_in_tx,pg_total,pg_longest_active_s,host_load1" > "$OUT"

while true; do
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  live=$(curl -s -o /dev/null -m 10 -w '%{http_code},%{time_total}' "$API/api/health/live" || echo "000,10")
  live_code=${live%,*}; live_ms=$(awk -v t="${live#*,}" 'BEGIN{printf "%d", t*1000}')
  health=$(curl -s -m 15 "$API/api/health" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("status","?"))
except Exception: print("no-json")' 2>/dev/null)
  remote=$(ssh -o ConnectTimeout=8 -o BatchMode=yes -i "$SSH_KEY" "$HOST" "$REMOTE" 2>/dev/null || echo "ssh-fail|||")
  IFS='|' read -r backend containers pg load1 <<<"$remote"
  read -r pg_active pg_idle_tx pg_total pg_longest <<<"${pg:-- - - -}"
  echo "$ts,$live_code,$live_ms,$health,$backend,\"$containers\",$pg_active,$pg_idle_tx,$pg_total,$pg_longest,$load1" | tee -a "$OUT"
  sleep "$INTERVAL"
done
