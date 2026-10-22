#!/bin/sh
# Odtworzenie kopii produkcji w stagingu — część wewnątrz kontenera `restore`
# (obraz z backup/Dockerfile: pg_restore 16, age, rclone, curl, jq).
#
# Uruchamia ją scripts/staging/restore_from_backup.sh, który podaje klucz
# prywatny age na stdin (z pęku kluczy macOS). Klucz ląduje tylko w tmpfs
# kontenera usuwanego po biegu, nigdy na dysku laptopa.
#
# Kolejność i źródła jak w backup/backup.sh (docs/disaster-recovery.md):
#   nexus/LATEST.json                                  → stempel ostatniego biegu
#   nexus/postgres/<dzień>/nexus-<stempel>.dump.age    → pg_restore + sanitize.sql
#   nexus/uploads/<dzień>/uploads-<stempel>.tar.gz.age → wolumen uploadów
#   nexus/qdrant/<dzień>/<kolekcja>-<stempel>.snapshot.age → Qdrant
#   nexus/candidate-documents/current/                 → lokalny S3 (rclone sync)
set -eu
set -o pipefail

fail() {
    echo "[restore] BŁĄD: $1" >&2
    exit 1
}
log() { echo "[restore] $1"; }

for v in BACKUP_S3_ENDPOINT BACKUP_S3_BUCKET BACKUP_S3_ACCESS_KEY BACKUP_S3_SECRET_KEY \
    POSTGRES_PASSWORD STAGING_S3_ACCESS_KEY STAGING_S3_SECRET_KEY; do
    eval "[ -n \"\${$v:-}\" ]" || fail "brak zmiennej $v (.env.staging.local)"
done

umask 077
KEY=/dev/shm/age-identity
cat > "$KEY"
grep -q '^AGE-SECRET-KEY-' "$KEY" || fail "na stdin nie ma klucza prywatnego age (AGE-SECRET-KEY-…)"
trap 'rm -f "$KEY"' EXIT

export RCLONE_CONFIG_OFFSITE_TYPE=s3
export RCLONE_CONFIG_OFFSITE_PROVIDER="${BACKUP_S3_PROVIDER:-Other}"
export RCLONE_CONFIG_OFFSITE_ENDPOINT="$BACKUP_S3_ENDPOINT"
export RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY"
export RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_KEY"
export RCLONE_CONFIG_OFFSITE_REGION="${BACKUP_S3_REGION:-eu-central-1}"
export RCLONE_CONFIG_STAGING_TYPE=s3
export RCLONE_CONFIG_STAGING_PROVIDER=Other
export RCLONE_CONFIG_STAGING_ENDPOINT=http://s3:7070
export RCLONE_CONFIG_STAGING_ACCESS_KEY_ID="$STAGING_S3_ACCESS_KEY"
export RCLONE_CONFIG_STAGING_SECRET_ACCESS_KEY="$STAGING_S3_SECRET_KEY"
export RCLONE_CONFIG_STAGING_REGION=us-east-1
export RCLONE_S3_NO_CHECK_BUCKET=true
export RCLONE_RETRIES=3
export RCLONE_LOW_LEVEL_RETRIES=5

SRC="offsite:${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX:-nexus}"
export PGPASSWORD="$POSTGRES_PASSWORD"
PG="psql -h postgres -U nexus -v ON_ERROR_STOP=1 -q"

decrypt() { # obiekt → odszyfrowany strumień na stdout
    rclone cat "$1" | age -d -i "$KEY"
}

manifest="$(rclone cat "${SRC}/LATEST.json")" || fail "nie mogę przeczytać ${SRC}/LATEST.json"
STAMP="$(echo "$manifest" | jq -r '.stamp')"
[ -n "$STAMP" ] && [ "$STAMP" != "null" ] || fail "LATEST.json bez stempla"
DAY="${STAMP%%T*}"
log "kopia z ${STAMP} (błędów w biegu backupu: $(echo "$manifest" | jq -r '.failures'))"
pg_status="$(echo "$manifest" | jq -r '.artefacts[] | select(.artefact=="postgres") | .status')"
[ "$pg_status" = "ok" ] || fail "artefakt postgres w tej kopii ma status '${pg_status}' — nie odtwarzam"

# ── 1. Postgres ──────────────────────────────────────────────────────────────
log "postgres: nowa baza nexus z nexus-${STAMP}.dump.age"
$PG -d postgres -c "DROP DATABASE IF EXISTS nexus WITH (FORCE)"
$PG -d postgres -c "CREATE DATABASE nexus"
# Bez --exit-on-error: zrzut z produkcji niesie m.in. komentarze rozszerzeń,
# których błąd nie psuje danych. Błędy liczymy i pokazujemy.
if ! decrypt "${SRC}/postgres/${DAY}/nexus-${STAMP}.dump.age" \
    | pg_restore -h postgres -U nexus -d nexus --no-owner --no-privileges 2>/tmp/pg_restore.err; then
    log "pg_restore zakończył się z błędami ($(grep -c 'error' /tmp/pg_restore.err || true)); ostatnie:"
    tail -n 5 /tmp/pg_restore.err >&2
fi
log "postgres: sanitizacja"
$PG -d nexus -f /staging/sanitize.sql
log "postgres: $($PG -d nexus -At -c "SELECT count(*) FROM candidates") kandydatów"

# ── 2. Uploady (wygenerowane dokumenty) ──────────────────────────────────────
log "uploady: uploads-${STAMP}.tar.gz.age"
find /uploads -mindepth 1 -delete
decrypt "${SRC}/uploads/${DAY}/uploads-${STAMP}.tar.gz.age" | tar -xzf - -C /uploads
chown -R 10001:10001 /uploads # appuser z backend/Dockerfile
log "uploady: $(find /uploads -type f | wc -l | tr -d ' ') plików"

# ── 3. Qdrant ────────────────────────────────────────────────────────────────
for obj in $(rclone lsf "${SRC}/qdrant/${DAY}/" --include "*-${STAMP}.snapshot.age"); do
    c="${obj%-${STAMP}.snapshot.age}"
    log "qdrant: kolekcja ${c}"
    decrypt "${SRC}/qdrant/${DAY}/${obj}" \
        | curl -fsS -X POST "http://qdrant:6333/collections/${c}/snapshots/upload?priority=snapshot" \
            -F "snapshot=@-;filename=${c}.snapshot" >/dev/null
done

# ── 4. Korpus CV (lokalny S3) ────────────────────────────────────────────────
# Przyrostowo: kolejne odtworzenia pobierają tylko nowe pliki. Źródło domyślne
# (decyzja Artura 22.10.2026) to bucket produkcji przez klucz TYLKO DO ODCZYTU
# (CV_SOURCE_*): pobieranie z lustra w B2 liczy się do dziennego limitu
# transakcji klasy B (backup.sh, RCLONE_S3_NO_HEAD), a ~136 tys. plików wyczerpuje
# go w kilkanaście minut. Bez CV_SOURCE_* zapasowo idzie lustro z B2.
CV_BUCKET=nexus-candidate-documents
if [ "${SKIP_CV:-0}" = "1" ]; then
    log "korpus CV: pominięty (SKIP_CV=1)"
else
    if [ -n "${CV_SOURCE_ENDPOINT:-}" ] && [ -n "${CV_SOURCE_ACCESS_KEY:-}" ] \
        && [ -n "${CV_SOURCE_SECRET_KEY:-}" ]; then
        export RCLONE_CONFIG_CVSRC_TYPE=s3
        export RCLONE_CONFIG_CVSRC_PROVIDER=Other
        export RCLONE_CONFIG_CVSRC_ENDPOINT="$CV_SOURCE_ENDPOINT"
        export RCLONE_CONFIG_CVSRC_ACCESS_KEY_ID="$CV_SOURCE_ACCESS_KEY"
        export RCLONE_CONFIG_CVSRC_SECRET_ACCESS_KEY="$CV_SOURCE_SECRET_KEY"
        export RCLONE_CONFIG_CVSRC_REGION="${CV_SOURCE_REGION:-eu-central-1}"
        CV_SRC="cvsrc:${CV_SOURCE_BUCKET:-$CV_BUCKET}"
    else
        CV_SRC="${SRC}/candidate-documents/current"
        log "korpus CV: brak CV_SOURCE_* — źródłem lustro w B2 (limit klasy B!)"
    fi
    rclone mkdir "staging:${CV_BUCKET}"
    log "korpus CV: rclone sync ${CV_SRC%%:*}: → staging:${CV_BUCKET}"
    rclone sync "$CV_SRC" "staging:${CV_BUCKET}" \
        --fast-list --transfers "${RESTORE_CV_TRANSFERS:-8}" \
        --max-duration "${RESTORE_CV_MAX_DURATION:-4h}" --stats-one-line --stats 2m \
        || log "korpus CV: sync niedokończony (kod $?) — wznowi się przy następnym biegu"
fi

log "gotowe: kopia ${STAMP}"
