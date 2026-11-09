#!/bin/sh
# Nocne dosłanie plików CV do lokalnego S3 stagingu — w kontenerze `restore`,
# uruchamia scripts/staging/nightly_sync.py. Baza jest co noc nowa, a bez tego
# kroku pliki zostawały z ostatniego pełnego odtworzenia: nowe rekordy dawały 503
# w podglądzie oryginału, a QC pisał „Brak tekstu oryginalnego CV”.
#
# Źródło to wyłącznie bucket produkcji przez klucz TYLKO DO ODCZYTU (CV_SOURCE_*).
# Bez lustra w B2 jako zapasu, inaczej niż w restore_inside.sh: bieg jest nocny, bez
# człowieka, a B2 ma dzienny limit pobrań klasy B.
#
# `copy --ignore-existing`, bo klucze nie zmieniają treści (uuid albo sha256), a tak
# kosztem nocy jest lista obu stron i pobranie samych brakujących plików. Bez `sync`:
# kasowanie zabrałoby pliki zapisane przez sesje na stagingu.
set -eu

fail() {
    echo "[pliki CV] BŁĄD: $1" >&2
    exit 1
}

for v in CV_SOURCE_ENDPOINT CV_SOURCE_ACCESS_KEY CV_SOURCE_SECRET_KEY \
    STAGING_S3_ACCESS_KEY STAGING_S3_SECRET_KEY; do
    eval "[ -n \"\${$v:-}\" ]" || fail "brak zmiennej $v (.env.staging.local)"
done

export RCLONE_CONFIG_CVSRC_TYPE=s3
export RCLONE_CONFIG_CVSRC_PROVIDER=Other
export RCLONE_CONFIG_CVSRC_ENDPOINT="$CV_SOURCE_ENDPOINT"
export RCLONE_CONFIG_CVSRC_ACCESS_KEY_ID="$CV_SOURCE_ACCESS_KEY"
export RCLONE_CONFIG_CVSRC_SECRET_ACCESS_KEY="$CV_SOURCE_SECRET_KEY"
export RCLONE_CONFIG_CVSRC_REGION="${CV_SOURCE_REGION:-eu-central-1}"
export RCLONE_CONFIG_STAGING_TYPE=s3
export RCLONE_CONFIG_STAGING_PROVIDER=Other
export RCLONE_CONFIG_STAGING_ENDPOINT=http://s3:7070
export RCLONE_CONFIG_STAGING_ACCESS_KEY_ID="$STAGING_S3_ACCESS_KEY"
export RCLONE_CONFIG_STAGING_SECRET_ACCESS_KEY="$STAGING_S3_SECRET_KEY"
export RCLONE_CONFIG_STAGING_REGION=us-east-1
# Świeży wolumen bez bucketu to sprawa pełnego odtworzenia: ma się skończyć błędem,
# a nie cichym pobieraniem całego korpusu w środku nocy.
export RCLONE_S3_NO_CHECK_BUCKET=true
export RCLONE_RETRIES=3
export RCLONE_LOW_LEVEL_RETRIES=5

# Statystyki w JSON, bo liczbę plików czyta nightly_sync.py. Błędy rclone niosą klucze
# z nazwami plików CV, więc całe wyjście idzie tylko do prywatnego logu. Limit czasu
# kończy bieg, a następna noc dosyła resztę.
exec rclone copy "cvsrc:${CV_SOURCE_BUCKET:-nexus-candidate-documents}" \
    "staging:nexus-candidate-documents" \
    --ignore-existing --fast-list --use-server-modtime \
    --transfers "${RESTORE_CV_TRANSFERS:-8}" \
    --max-duration "${SYNC_CV_MAX_DURATION:-1h}" \
    --use-json-log --stats 1h --stats-log-level NOTICE
