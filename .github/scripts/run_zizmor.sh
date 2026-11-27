#!/usr/bin/env bash
# zizmor na całym repo (workflowy + dependabot.yml): wynik JSON dla zapadki,
# opcjonalnie SARIF dla DefectDojo.
#   run_zizmor.sh <wynik.json> [<wynik.sarif>]
# Audyty online (znane podatne wersje akcji, commit spoza repo akcji) pytają
# API GitHuba tokenem z GH_TOKEN; jeden niedostępny endpoint kończy cały bieg
# błędem „no audit was performed”, stąd 3 próby. Kod wyjścia zizmora przy
# znaleziskach (`--no-exit-codes`) pomijamy — o wyniku decyduje zapadka.
set -euo pipefail

json_out="$1"
sarif_out="${2:-}"

for attempt in 1 2 3; do
  if zizmor --quiet --no-exit-codes --no-progress --format json . > "$json_out" \
      && { [ -z "$sarif_out" ] || zizmor --quiet --no-exit-codes --no-progress --format sarif . > "$sarif_out"; }; then
    exit 0
  fi
  echo "::warning::zizmor nie zakończył skanu (próba $attempt z 3) — zwykle chwilowy błąd API GitHuba."
  sleep 20
done
echo "::error::zizmor nie zakończył skanu — błąd API GitHuba albo skanera; ponów job."
exit 1
