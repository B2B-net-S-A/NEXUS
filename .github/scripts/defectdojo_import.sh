#!/usr/bin/env bash
# Import raportów skanerów do DefectDojo (reimport = deduplikacja między biegami).
#   defectdojo_import.sh "<scan_type>" "<tytuł testu>" <plik> [kolejna trójka …]
#
# DefectDojo stoi na serwerze bezpieczeństwa bez publicznego adresu: runner
# podnosi tunel WireGuard z konfiguracji peera w DEFECTDOJO_WG_CONF (job
# podaje swój sekret `DEFECTDOJO_WG_CONF_<JOB>`; peer widzi w tunelu
# wyłącznie DefectDojo) i woła DEFECTDOJO_URL (domyślnie adres w
# tunelu). Token DEFECTDOJO_TOKEN: konto `ci-import`, rola Writer tylko na
# produkcie NEXUS. Bez sekretów krok kończy się notką — import jest pusty,
# nie czerwony. Produkt, typ produktu i engagement zakłada sesja SOC z góry;
# `auto_create_context` dokłada tylko brakujące testy.
#
# Repo i logi Actions są publiczne: log pokazuje tylko kod HTTP i liczby
# ze `statistics` odpowiedzi, nigdy treść znalezisk ani adres serwera
# (wyjście `wg-quick` idzie do /dev/null). Raport idzie wprost z joba, bez
# artefaktu (artefakty publicznego repo pobierze każdy zalogowany).
# `close_old_findings`: znalezisko, którego nie ma w nowym raporcie danego
# testu, DefectDojo zamyka. → docs/claude/podstawy/skanery-bezpieczenstwa.md
set -uo pipefail

if [ $(( $# % 3 )) -ne 0 ] || [ $# -eq 0 ]; then
  echo "użycie: $0 \"<scan_type>\" \"<tytuł testu>\" <plik> [...]" >&2
  exit 2
fi
if [ -z "${DEFECTDOJO_TOKEN:-}" ] || [ -z "${DEFECTDOJO_WG_CONF:-}" ]; then
  echo "::notice title=DefectDojo::Brak DEFECTDOJO_TOKEN/DEFECTDOJO_WG_CONF — import pominięty."
  exit 0
fi
url="${DEFECTDOJO_URL:-http://10.66.0.1:8080}"
url="${url%/}"

tunnel_up() {
  if ! command -v wg-quick >/dev/null 2>&1; then
    { sudo apt-get update -q && sudo apt-get install -y -q wireguard-tools; } >/dev/null 2>&1 || return 1
  fi
  # umask 077 przed zapisem: plik z kluczem prywatnym peera nigdy nie jest
  # czytelny dla innych, nawet przez chwilę.
  printf '%s\n' "$DEFECTDOJO_WG_CONF" \
    | sudo sh -c 'umask 077; mkdir -p /etc/wireguard; cat > /etc/wireguard/dojo.conf' || return 1
  sudo wg-quick up dojo >/dev/null 2>&1
}
tunnel_down() {
  sudo wg-quick down dojo >/dev/null 2>&1 || true
  sudo rm -f /etc/wireguard/dojo.conf
}
trap tunnel_down EXIT

if ! tunnel_up; then
  echo "::warning title=DefectDojo::Tunel WireGuard do serwera bezpieczeństwa się nie podniósł — import pominięty."
  exit 1
fi

response="${RUNNER_TEMP:-/tmp}/defectdojo-response.json"
status=0
while [ $# -gt 0 ]; do
  scan_type="$1" test_title="$2" report="$3"
  shift 3
  if [ ! -s "$report" ]; then
    echo "::warning title=DefectDojo::Brak raportu ${report} — „${test_title}” pominięty."
    status=1
    continue
  fi
  code=$(curl -sS -o "$response" -w '%{http_code}' \
    --retry 3 --retry-delay 10 --retry-all-errors --connect-timeout 20 --max-time 300 \
    -H "Authorization: Token ${DEFECTDOJO_TOKEN}" \
    --form-string "scan_type=${scan_type}" \
    --form-string "test_title=${test_title}" \
    --form-string "product_type_name=NEXUS" \
    --form-string "product_name=NEXUS" \
    --form-string "engagement_name=CI tygodniowy" \
    --form-string "auto_create_context=true" \
    --form-string "close_old_findings=true" \
    --form-string "minimum_severity=Info" \
    --form-string "active=true" \
    --form-string "verified=false" \
    --form-string "branch_tag=${GITHUB_REF_NAME:-main}" \
    --form-string "commit_hash=${GITHUB_SHA:-}" \
    --form-string "build_id=${GITHUB_RUN_ID:-}" \
    --form-string "source_code_management_uri=${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}" \
    -F "file=@${report}" \
    "${url}/api/v2/reimport-scan/" 2>/dev/null) || code="000"
  if [ "$code" = "201" ] || [ "$code" = "200" ]; then
    # Same liczby ze `statistics.delta`, bez tytułów i opisów znalezisk.
    stats=$(python3 - "$response" <<'PY' 2>/dev/null || true
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
delta = (data.get("statistics") or {}).get("delta") or {}
counts = {k: (v or {}).get("total", 0) for k, v in delta.items() if isinstance(v, dict)}
print(" ".join(f"{k}={v}" for k, v in sorted(counts.items())))
PY
)
    echo "DefectDojo: „${test_title}” zaimportowany (HTTP ${code}) ${stats}"
  else
    echo "::warning title=DefectDojo::Import „${test_title}” nie przeszedł (HTTP ${code}) — szczegóły w panelu DefectDojo, nie w logu."
    status=1
  fi
  rm -f "$response"
done
exit "$status"
