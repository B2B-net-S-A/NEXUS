#!/bin/sh
# Budzik okna wdrożeń NEXUSA (15.10.2026).
#
# Wdrożenia idą tylko 18:00–08:00 czasu warszawskiego (decyzja Artura
# 14.10.2026). Merge'e z dnia odracza workflow Deploy, a wdrażać miał je
# wieczorny `schedule` GitHuba. Ten w tym repo przychodzi z 3–9 h opóźnieniem
# albo wcale: 15.10 żaden z wieczornych slotów nie przyszedł do 21:30
# (dzienne merge'e wdrożył dopiero ręczny bieg), a godzinny `uptime-probe`
# odpala się ok. 4 razy na dobę. Ten kontener o 18:05, 20:05 i 22:05 uruchamia
# Deploy przez API GitHuba: `workflow_dispatch` z `window_slot=true` zachowuje
# się jak `schedule` (bramka CI Gate, okno ciszy, pominięcie rebuildu, gdy
# produkcja ma już HEAD maina). Kolejne sloty to ponowienie, gdy wcześniejszy
# deploy padł; przy zielonym kończą się na koalescencji. Cron GitHuba zostaje
# jako zapas.
#
# Token: fine-grained PAT tylko do tego repo, „Actions: read and write” —
# pozwala uruchomić KAŻDY workflow repo, także zmianę zmiennych produkcji.
# Dlatego leży w pliku hosta (`/etc/nexus-deploy-window/token`, właściciel
# uid 10001, 0400) zamontowanym tylko do tego kontenera i tylko do odczytu.
# NIE w skarbcu Coolify: Coolify zapisuje skarbiec do `.env`, a backend
# i frontend mają `env_file: .env` (przegląd bezpieczeństwa PR #2252).
# Plik czytamy przy każdym slocie — wgranie albo wymiana tokenu nie wymaga
# restartu; brak pliku = slot pominięty z wpisem w logu.
set -eu

SLOTS="18:05 20:05 22:05"
# Kanoniczna nazwa po przeniesieniu repo do organizacji — stara
# `artur-t-96/Nexus` daje przekierowanie, za którym POST nie idzie.
REPO="${DEPLOY_WINDOW_REPO:-B2B-net-S-A/NEXUS}"
TOKEN_FILE="/run/deploy-window/token"
export TZ=Europe/Warsaw

log() {
    echo "[deploy-window] $(date '+%F %T %Z') $*"
}

# Zwykły, niepusty i czytelny plik — `-s` sam przepuściłby katalog.
token_ready() {
    [ -f "$TOKEN_FILE" ] && [ -s "$TOKEN_FILE" ] && [ -r "$TOKEN_FILE" ]
}

# 204 = Deploy uruchomiony. 4xx = zły, wygasły albo za słaby token — ponowienie
# nic nie da. Błąd sieci i 5xx ponawiamy dwa razy co minutę.
dispatch() {
    if ! token_ready; then
        log "slot $1: brak czytelnego tokenu w $TOKEN_FILE — pomijam"
        return 1
    fi
    attempt=1
    while :; do
        # Bez starej odpowiedzi: po błędzie sieci log pokazałby treść z poprzedniego slotu.
        rm -f "${TMPDIR:-/tmp}/dispatch-response"
        # Nagłówek z tokenem przez `--config -` (stdin), nie w argumentach —
        # argumenty curla widać w `ps` i `docker top`.
        code="$(printf 'header = "Authorization: Bearer %s"\n' "$(tr -d ' \r\n' < "$TOKEN_FILE")" \
            | curl --config - -sS -o "${TMPDIR:-/tmp}/dispatch-response" -w '%{http_code}' \
                --max-time 30 -X POST \
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

if token_ready; then
    log "budzik włączony, sloty: $SLOTS"
else
    log "budzik czeka na token w $TOKEN_FILE (sloty: $SLOTS)"
fi
fired=""
while :; do
    tick "$(date +%H:%M)" "$(date +%F)"
    sleep 20
done
