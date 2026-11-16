#!/bin/sh
# Zajętość wolumenu kopii zapasowych dla `/api/health` (audyt 22.09, PROD-01).
#
# Backend widzi tylko `/` kontenera, a kopie leżą na osobnym wolumenie. Ten skrypt
# zapisuje `backup-volume.json` do `/var/lib/nexus-status`, który kontener backendu
# montuje read-only jako `/run/nexus-host-status` (docker-compose.yml). Czyta go
# `backend/app/services/host_status.py`; plik starszy niż 2 h = `null` w health.
# Cron miał powstać 22.09, ale nigdy nie trafił na host: katalog był pusty do 16.11.
#
# Tylko odczyt `df` i zapis jednego pliku: nic nie kasuje, nie rusza Dockera.
# Opis: docs/claude/podstawy/sonda-wolumenu-kopii-na-hoscie.md
set -eu

BACKUP_PATH="${NEXUS_BACKUP_PATH:-/var/backups}"
STATUS_DIR="${NEXUS_STATUS_DIR:-/var/lib/nexus-status}"
OUT="$STATUS_DIR/backup-volume.json"

# `/var/backups` to symlink na katalog na wolumenie; `df` liczy system plików celu.
target=$(readlink -f "$BACKUP_PATH")
line=$(df -P -k "$target" | tail -1)
set -- $line
avail_kb=$4
pcent=$(printf '%s' "$5" | tr -dc '0-9')
mount=$6

# Odpięty wolumen = katalog na `/`. Wtedy nie zapisujemy nic: plik się zestarzeje
# i health da `null` zamiast udawać, że procent dysku systemowego to kopie.
if [ "$mount" = "/" ]; then
  echo "nexus-backup-volume-status: $target leży na /, nie na wolumenie kopii — pomijam" >&2
  exit 1
fi
case "$pcent$avail_kb" in
  ''|*[!0-9]*) echo "nexus-backup-volume-status: nieczytelne df: $line" >&2; exit 1 ;;
esac

avail_gb=$(awk -v kb="$avail_kb" 'BEGIN { printf "%.1f", kb / 1048576 }')
checked_at=$(date -u +%FT%TZ)

mkdir -p "$STATUS_DIR"
tmp=$(mktemp "$STATUS_DIR/.backup-volume.XXXXXX")
trap 'rm -f "$tmp"' EXIT
printf '{"used_percent": %s, "avail_gb": %s, "checked_at": "%s", "mount": "%s"}\n' \
  "$pcent" "$avail_gb" "$checked_at" "$mount" >"$tmp"
# mktemp daje 0600, a backend w kontenerze czyta jako appuser (uid 10001).
chmod 0644 "$tmp"
mv -f "$tmp" "$OUT"
trap - EXIT
