#!/usr/bin/env bash
# Trivy na obrazach produkcji (bieg tygodniowy, `security-weekly.yml`).
#   trivy_images.sh <lista obrazów> <katalog raportów>
# Lista: wiersz „<źródło> <obraz>”, źródło `docker` (zbudowany lokalnie
# z wdrożonego SHA) albo `remote` (rejestr, linux/amd64 jak serwer).
#
# Dla każdego obrazu dwa przebiegi na tej samej bazie:
#   * `<katalog>/trivy-<obraz>.json` — HIGH/CRITICAL z poprawką, BEZ wyjątków
#     (do DefectDojo, który pokazuje też to, co zapadka przepuszcza);
#   * ten sam skan z `.trivyignore-images` — o wyniku decyduje ten licznik.
# Wyjątki z terminem `exp:` jak w `.trivyignore`; po terminie znów czerwień.
# Osobny plik, bo wspólny `.trivyignore` ukryłby tę samą podatność także
# w skanie zależności na PR-ach (`ci.yml`, job „Trivy + hadolint”).
# Raport w podsumowaniu biegu ma tylko obraz, identyfikator, paczkę i wersje.
set -uo pipefail

list="$1"
outdir="$2"
ignorefile="${TRIVY_IMAGES_IGNOREFILE:-.trivyignore-images}"
mkdir -p "$outdir"

total=0
failed=0
summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
{
  echo "### Trivy — obrazy produkcji (HIGH/CRITICAL z dostępną poprawką)"
  echo
  echo "| Obraz | Nowe (poza \`$ignorefile\`) | Wszystkie z poprawką |"
  echo "|---|---|---|"
} >> "$summary"
details=$(mktemp)

while read -r src image; do
  [ -n "${src:-}" ] && [ "${src#\#}" = "$src" ] || continue
  safe=$(printf '%s' "$image" | tr '/:@' '___')
  args=(image --quiet --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --image-src "$src")
  if [ "$src" = "remote" ]; then
    args+=(--platform linux/amd64)
  fi
  ok=true
  for attempt in 1 2 3; do
    if trivy "${args[@]}" --format json --output "$outdir/trivy-$safe.json" "$image" \
        && trivy "${args[@]}" --ignorefile "$ignorefile" --format json --output "$outdir/gate-$safe.json" "$image"; then
      ok=true
      break
    fi
    ok=false
    echo "::warning::Trivy nie przeskanował $image (próba $attempt z 3)."
    sleep 20
  done
  if [ "$ok" != true ]; then
    echo "::error::Trivy nie przeskanował $image — rejestr albo baza podatności niedostępne."
    echo "| \`$image\` | **błąd skanu** | — |" >> "$summary"
    failed=$((failed + 1))
    continue
  fi
  all=$(jq '[.Results[]?.Vulnerabilities[]?] | length' "$outdir/trivy-$safe.json")
  new=$(jq '[.Results[]?.Vulnerabilities[]?] | length' "$outdir/gate-$safe.json")
  echo "| \`$image\` | **$new** | $all |" >> "$summary"
  echo "Trivy $image: nowe $new, wszystkie z poprawką $all"
  if [ "$new" -gt 0 ]; then
    total=$((total + new))
    {
      echo
      echo "#### \`$image\`"
      echo
      echo "| Identyfikator | Paczka | Zainstalowana | Poprawka | Waga |"
      echo "|---|---|---|---|---|"
      jq -r '[.Results[]?.Vulnerabilities[]?] | unique_by(.VulnerabilityID + .PkgName) | .[:60][]
        | "| `\(.VulnerabilityID)` | `\(.PkgName)` | \(.InstalledVersion) | \(.FixedVersion // "") | \(.Severity) |"' \
        "$outdir/gate-$safe.json"
    } >> "$details"
  fi
  rm -f "$outdir/gate-$safe.json"
done < "$list"

cat "$details" >> "$summary"
rm -f "$details"
if [ "$failed" -gt 0 ] || [ "$total" -gt 0 ]; then
  echo "::error::Trivy obrazów: $total nowych HIGH/CRITICAL z poprawką, $failed obrazów bez skanu — tabela w podsumowaniu biegu. Podbij obraz albo dopisz uzasadniony wyjątek z terminem do $ignorefile."
  exit 1
fi
echo "Trivy obrazów: brak nowych HIGH/CRITICAL z dostępną poprawką."
