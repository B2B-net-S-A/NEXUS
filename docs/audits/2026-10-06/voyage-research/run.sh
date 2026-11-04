#!/usr/bin/env bash
# Jednorazowy kontener z obrazem backendu: bez entrypointu (migracje), limit CPU/RAM.
set -euo pipefail
B=$(docker ps --format "{{.Names}}" | grep "^backend-ocgkwcbovpve9wvf9smxl0kx" | head -1)
IMG=$(docker inspect "$B" --format "{{.Config.Image}}")
NET=$(docker inspect "$B" --format "{{range \$k,\$v := .NetworkSettings.Networks}}{{\$k}}{{end}}")
exec docker run --rm --name "voyage-research-$$" --cpus 3 --memory 7g \
  --network "$NET" \
  --env-file <(docker inspect "$B" --format "{{range .Config.Env}}{{println .}}{{end}}" | grep -v "^$") \
  -e PYTHONPATH=/app:/vr -e PYTHONDONTWRITEBYTECODE=1 \
  -v /root/voyage-research:/vr \
  -w /vr --entrypoint python "$IMG" "$@"
