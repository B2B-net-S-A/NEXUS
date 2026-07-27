#!/bin/sh
# Liveness probe for the backup sidecar.
#
# Why this exists: the service had no healthcheck at all, so the two ways it
# actually breaks were both invisible from `docker ps` — which showed "Up 3
# weeks" in either case:
#
#   1. The scheduler loop dies or the container wedges. Nothing runs again,
#      ever, and nothing says so.
#   2. A run hangs (rclone against an unresponsive endpoint, a `pg_dump` that
#      never returns). The container looks busy forever and the night's backup
#      never completes.
#
# Both are detected here: loop.sh runs a detached ticker that refreshes
# $HEARTBEAT every 30s for the container's whole life, and marks a run in
# progress with $RUN_MARKER (containing its start epoch).
#
# Deliberately says nothing about whether backups are SUCCEEDING — a green
# container with a kill-switched or silently failing backup is exactly the
# reassurance this codebase has been burned by. Success is monitored off-host
# from LATEST.json (see .github/workflows/uptime-probe.yml), because a probe
# that lives on the machine being backed up cannot report on the disaster that
# takes that machine.
set -eu

HEARTBEAT=/tmp/backup-heartbeat
RUN_MARKER=/tmp/backup-run-started

# Ticker period is 30s; 120s tolerates a slow or briefly starved container
# without tolerating a dead one.
MAX_HEARTBEAT_AGE="${BACKUP_MAX_HEARTBEAT_AGE_SECONDS:-120}"
# A full run is minutes for Postgres/Qdrant, and up to BACKUP_CV_MAX_DURATION
# (default 6h) for the CV mirror. 8h leaves headroom over that cap; beyond it
# the run is not slow, it is stuck.
MAX_RUN="${BACKUP_MAX_RUN_SECONDS:-28800}"

now="$(date -u +%s)"

[ -f "$HEARTBEAT" ] || {
    echo "no heartbeat file — the scheduler loop never started" >&2
    exit 1
}

# `stat -c %Y` is available in busybox (postgres:16-alpine).
beat="$(stat -c %Y "$HEARTBEAT")"
age=$(( now - beat ))
if [ "$age" -gt "$MAX_HEARTBEAT_AGE" ]; then
    echo "heartbeat is ${age}s old (max ${MAX_HEARTBEAT_AGE}s) — loop is dead or wedged" >&2
    exit 1
fi

if [ -f "$RUN_MARKER" ]; then
    started="$(cat "$RUN_MARKER" 2>/dev/null || echo "$now")"
    running=$(( now - started ))
    if [ "$running" -gt "$MAX_RUN" ]; then
        echo "a backup run has been in progress for ${running}s (max ${MAX_RUN}s) — hung" >&2
        exit 1
    fi
fi

exit 0
