#!/usr/bin/env bash
# Issue-alarm dla workflowów monitoringu: jedno otwarte issue na rodzaj awarii.
#
#   alert_issue.sh open    <marker> <plik-z-treścią> [prefiks]
#   alert_issue.sh resolve <marker> [zdanie]
#
# `open`    — jest otwarte issue z <marker> w tytule → komentarz z treścią pliku;
#             nie ma → nowe issue „<prefiks> <marker>” (prefiks domyślnie ⚠️).
# `resolve` — każde otwarte issue z <marker> w tytule dostaje komentarz i jest
#             zamykane. Nigdy nie kończy się błędem: zamknięcie alarmu to
#             sprzątanie, a nie powód, żeby zielony bieg zrobił się czerwony.
#
# Dlaczego skrypt, a nie kolejna kopia w YAML-u (audyt 22.09.2026, OPS-N08):
# alarmy otwierały issue, ale nic ich nie zamykało — #825 („host disk high”)
# wisiało od lipca i #1413 od 8.09, choć warunek dawno minął. Alarm, który
# nigdy nie gaśnie, przestaje cokolwiek znaczyć. Marker musi być DOKŁADNIE ten
# sam przy otwieraniu i zamykaniu — stąd jedno miejsce z logiką dopasowania.
#
# Dopasowanie: wyszukiwarka GitHuba jest rozmyta („in:title” zwraca też
# podobne tytuły), więc wynik jest dodatkowo filtrowany jq po DOSŁOWNYM
# podciągu markera. Stare issue mają różne prefiksy (⚠️ / 🚨) — podciąg je
# obejmuje.
#
# Środowisko: GH_TOKEN (issues: write), REPO (domyślnie GITHUB_REPOSITORY),
# RUN_URL (opcjonalnie — link do biegu w komentarzu).

set -uo pipefail

usage() {
  echo "użycie: alert_issue.sh open <marker> <plik-z-treścią> [prefiks] | resolve <marker> [zdanie]" >&2
  exit 2
}

[ "$#" -ge 2 ] || usage
action="$1"
marker="$2"
[ -n "$marker" ] || usage
repo="${REPO:-${GITHUB_REPOSITORY:-}}"
if [ -z "$repo" ]; then
  echo "::error::alert_issue.sh: brak REPO/GITHUB_REPOSITORY" >&2
  exit 2
fi

# Numery otwartych issue z markerem w tytule, od najnowszego. Pusty wynik =
# brak takich issue. Kod 1 = nie udało się zapytać GitHuba.
matching_issues() {
  local raw
  if ! raw=$(gh issue list --repo "$repo" --state open --limit 50 \
      --search "\"$marker\" in:title" --json number,title); then
    return 1
  fi
  printf '%s' "$raw" | jq -r --arg m "$marker" \
    '[.[] | select(.title | contains($m))] | sort_by(-.number) | .[].number'
}

case "$action" in
  open)
    [ "$#" -ge 3 ] || usage
    body_file="$3"
    prefix="${4:-⚠️}"
    if [ ! -s "$body_file" ]; then
      echo "::error::alert_issue.sh open: pusty albo brak pliku z treścią ($body_file)" >&2
      exit 2
    fi
    if ! numbers=$(matching_issues); then
      # Lepiej ryzykować duplikat niż zgubić alarm.
      echo "::warning::Nie udało się odczytać otwartych issue — zakładam nowe." >&2
      numbers=""
    fi
    existing=$(printf '%s\n' "$numbers" | sed -n '1p')
    if [ -n "$existing" ]; then
      gh issue comment "$existing" --repo "$repo" --body-file "$body_file" || exit 1
      echo "Alarm „${marker}”: komentarz w #${existing}."
    else
      gh issue create --repo "$repo" --title "${prefix} ${marker}" --body-file "$body_file" || exit 1
      echo "Alarm „${marker}”: nowe issue."
    fi
    ;;
  resolve)
    reason="${3:-Warunek alarmu już nie występuje.}"
    if ! numbers=$(matching_issues); then
      echo "::warning::alert_issue.sh resolve: nie udało się odczytać issue — alarm „${marker}” zostaje otwarty." >&2
      exit 0
    fi
    if [ -z "$numbers" ]; then
      echo "Alarm „${marker}”: brak otwartych issue."
      exit 0
    fi
    comment="${reason}"
    if [ -n "${RUN_URL:-}" ]; then
      comment="${comment}

Zielony bieg: ${RUN_URL}"
    fi
    comment="${comment}

_Zamknięte automatycznie przez \`.github/scripts/alert_issue.sh\`. Jeśli problem wróci, kolejny czerwony bieg otworzy nowe issue._"
    while IFS= read -r number; do
      [ -n "$number" ] || continue
      if gh issue close "$number" --repo "$repo" --reason completed --comment "$comment"; then
        echo "Alarm „${marker}”: zamknięto #${number}."
      else
        echo "::warning::Nie udało się zamknąć #${number} (alarm „${marker}”)." >&2
      fi
    done <<< "$numbers"
    exit 0
    ;;
  *)
    usage
    ;;
esac
