#!/usr/bin/env bash
# Jednorazowy kontener z obrazem backendu, baza TYLKO DO ODCZYTU (ro_boot), limit CPU/RAM.
set -euo pipefail
B=$(docker ps --format "{{.Names}}" | grep "^backend-ocgkwcbovpve9wvf9smxl0kx" | head -1)
IMG=$(docker inspect "$B" --format "{{.Config.Image}}")
NET=$(docker inspect "$B" --format "{{range \$k,\$v := .NetworkSettings.Networks}}{{\$k}}{{end}}")
exec docker run --rm --name "nexus-search-research-$$" --cpus 3 --memory 6g \
  --network "$NET" \
  --env-file <(docker inspect "$B" --format "{{range .Config.Env}}{{println .}}{{end}}" | grep -v "^$") \
  -e PYTHONPATH=/app:/research -e PYTHONDONTWRITEBYTECODE=1 -e RESEARCH_ARGS="${RESEARCH_ARGS:-}" \
  -v /root/nexus-search-research:/research \
  -w /app --entrypoint python "$IMG" "$@"
