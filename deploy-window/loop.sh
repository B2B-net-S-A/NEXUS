#!/bin/sh
# Budzik okna wdrożeń NEXUSA (15.10.2026).
#
# Wdrożenia idą tylko 19:00–07:00 czasu warszawskiego (decyzja Artura
# 14.10.2026). Merge'e z dnia odracza workflow Deploy, a wdrażać miał je
# wieczorny `schedule` GitHuba. Ten w tym repo przychodzi z 3–9 h opóźnieniem
# albo wcale: 15.10 żaden z wieczornych slotów nie przyszedł do 21:30
# (dzienne merge'e wdrożył dopiero ręczny bieg), a godzinny `uptime-probe`
# odpala się ok. 4 razy na dobę. Ten kontener o 19:05, 21:05 i 23:05 uruchamia
# Deploy przez API GitHuba: `workflow_dispatch` z `window_slot=true` zachowuje
# się jak `schedule` (bramka CI Gate, okno ciszy, pominięcie rebuildu, gdy
# produkcja ma już HEAD maina). Kolejne sloty to ponowienie, gdy wcześniejszy
# deploy padł; przy zielonym kończą się na koalescencji. Cron GitHuba zostaje
# jako zapas.
#
# Token: fine-grained PAT tylko do tego repo, uprawnienie „Actions: read and
# write”. Dostaje go wyłącznie ten kontener — backend wystawiony do internetu
# nie. Brak tokenu = budzik śpi, zamiast restartować się w kółko.
set -eu

SLOTS="19:05 21:05 23:05"
REPO="${DEPLOY_WINDOW_REPO:-artur-t-96/Nexus}"
TOKEN="${DEPLOY_WINDOW_GITHUB_TOKEN:-}"
export TZ=Europe/Warsaw

log() {
    echo "[deploy-window] $(date '+%F %T %Z') $*"
}

# 204 = Deploy uruchomiony. 4xx = zły, wygasły albo za słaby token — ponowienie
# nic nie da. Błąd sieci i 5xx ponawiamy dwa razy co minutę.
dispatch() {
    attempt=1
    while :; do
        code="$(curl -sS -o "${TMPDIR:-/tmp}/dispatch-response" -w '%{http_code}' \
            --max-time 30 -X POST \
            -H "Authorization: Bearer $TOKEN" \
            -H "Accept: application/vnd.github+json" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            -d '{"ref":"main","inputs":{"window_slot":"true"}}' \
            "https://api.github.com/repos/$REPO/actions/workflows/deploy.yml/dispatches")" \
            || code="000"
        if [ "$code" = "204" ]; then
            log "slot $1: Deploy uruchomiony"
            return 0
        fi
        detail="$(head -c 200 "${TMPDIR:-/tmp}/dispatch-response" 2>/dev/null | tr -d '\r\n' || true)"
        log "slot $1: próba $attempt/3 — HTTP $code $detail"
        case "$code" in
            4*) return 1 ;;
        esac
        if [ "$attempt" -ge 3 ]; then
            return 1
        fi
        attempt=$((attempt + 1))
        sleep 60
    done
}

# Pętla patrzy na zegar co 20 s, więc ta sama minuta przychodzi 2–3 razy;
# `fired` pilnuje, żeby slot odpalił raz na dobę.
tick() {
    for slot in $SLOTS; do
        if [ "$1" = "$slot" ] && [ "$fired" != "$2 $slot" ]; then
            fired="$2 $slot"
            dispatch "$slot" || true
        fi
    done
}

if [ -z "$TOKEN" ]; then
    log "brak DEPLOY_WINDOW_GITHUB_TOKEN — budzik wyłączony"
    while :; do
        sleep 86400
    done
fi

log "budzik włączony, sloty: $SLOTS"
fired=""
while :; do
    tick "$(date +%H:%M)" "$(date +%F)"
    sleep 20
done
