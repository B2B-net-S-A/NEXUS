#!/usr/bin/env bash
# Kopia produkcji → staging na laptopie (docs/staging-laptop-plan.md, etap 1).
#
# Źródło to kopia offsite z backup/backup.sh, nie baza na żywo: produkcja nie
# dostaje żadnego obciążenia, a każde odtworzenie sprawdza przy okazji, że
# backup naprawdę da się odtworzyć.
#
# Wymaga:
#   - .env.staging.local w katalogu repo (wzór: scripts/staging/env.staging.example),
#     w tym klucza B2 TYLKO DO ODCZYTU (BACKUP_S3_*);
#   - klucza prywatnego age w pęku kluczy macOS:
#       security add-generic-password -s nexus-backup-age -a "$USER" -w 'AGE-SECRET-KEY-…'
#
# Użycie:
#   scripts/staging/restore_from_backup.sh            # baza, uploady, Qdrant, korpus CV
#   SKIP_CV=1 scripts/staging/restore_from_backup.sh  # bez korpusu CV (37 GB)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="$ROOT/.env.staging.local"
[ -f "$ENV_FILE" ] || { echo "Brak $ENV_FILE — skopiuj scripts/staging/env.staging.example" >&2; exit 1; }

compose() { docker compose -f "$ROOT/docker-compose.staging.yml" --env-file "$ENV_FILE" "$@"; }

identity="$(security find-generic-password -s nexus-backup-age -a "$USER" -w)" || {
    echo "Brak klucza age w pęku kluczy (usługa nexus-backup-age)" >&2
    exit 1
}

echo "[restore] zatrzymuję backend i frontend stagingu"
compose stop backend frontend >/dev/null 2>&1 || true
compose up -d --wait postgres qdrant s3

echo "[restore] odtwarzam w kontenerze restore"
printf '%s\n' "$identity" | compose --profile restore run --rm -T -e SKIP_CV="${SKIP_CV:-0}" restore
unset identity

echo "[restore] start backendu i frontendu (migracje dnia biegną na kopii)"
GIT_SHA="$(git -C "$ROOT" rev-parse HEAD)" compose up -d --build --wait backend frontend mailpit
curl -fsS http://127.0.0.1:8100/api/health | jq '{status, version}'
