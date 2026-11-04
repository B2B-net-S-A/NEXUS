#!/usr/bin/env bash
# Jak run.sh, ale z kodem gałęzi (/root/nexus-branch/backend) zamiast /app — pomiar przed merge.
set -euo pipefail
B=$(docker ps --format "{{.Names}}" | grep "^backend-ocgkwcbovpve9wvf9smxl0kx" | head -1)
IMG=$(docker inspect "$B" --format "{{.Config.Image}}")
NET=$(docker inspect "$B" --format "{{range \$k,\$v := .NetworkSettings.Networks}}{{\$k}}{{end}}")
exec docker run --rm --name "nexus-search-branch-$$" --cpus 3 --memory 6g \
  --network "$NET" \
  --env-file <(docker inspect "$B" --format "{{range .Config.Env}}{{println .}}{{end}}" | grep -v "^$") \
  -e PYTHONPATH=/branch:/research -e PYTHONDONTWRITEBYTECODE=1 -e RESEARCH_ARGS="${RESEARCH_ARGS:-}" \
  -v /root/nexus-search-research:/research \
  -v /root/nexus-branch/backend:/branch:ro -w /branch --entrypoint python "$IMG" "$@"
