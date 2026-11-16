#!/bin/sh
# Sprzątanie cache buildów Dockera na hoście produkcji NEXUSA.
#
# Decyzja Artura z 16.11.2026. Coolify (4.7.5) czyści cache buildów co godzinę,
# ale pomija ten krok, gdy w kolejce stoi jakiekolwiek wdrożenie („Skipped: the
# build cache was not pruned because deployment … is queued or running”). Przy
# serii wdrożeń z kolejki merge'ów cache rośnie ok. 30 GB w 4 h: 16.11 o 03:00
# dysk miał 94%, a awaria 17.07 przyszła przy 98,8%.
#
# Rusza tylko cache buildów: bez kontenerów (coolify-db!), wolumenów i obrazów.
# `until` zostawia cache użyty w ostatniej godzinie, więc trwający build go nie traci.
# Opis: docs/claude/podstawy/sprzatanie-cache-buildow-na-hoscie.md
set -eu

THRESHOLD="${NEXUS_PRUNE_THRESHOLD:-70}"
UNTIL="${NEXUS_PRUNE_UNTIL:-1h}"
LOG="${NEXUS_PRUNE_LOG:-/var/log/nexus-build-cache.log}"

exec 9>/run/nexus-build-cache.lock
flock -n 9 || exit 0

disk_pct() { df --output=pcent / | tail -1 | tr -dc '0-9'; }

before=$(disk_pct)
[ "$before" -gt "$THRESHOLD" ] || exit 0

if out=$(docker builder prune -af --filter "until=$UNTIL" 2>&1); then
  status=ok
else
  status=failed
fi
after=$(disk_pct)
echo "$(date -u +%FT%TZ) ${status} before=${before}% after=${after}% threshold=${THRESHOLD}% until=${UNTIL} $(printf '%s' "$out" | tail -1)" >>"$LOG"
