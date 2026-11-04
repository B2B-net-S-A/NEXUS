#!/usr/bin/env bash
# Hasło konta E2E: nowe, losowe, nikt go nie widzi. Pierwsze uruchomienie zamienia
# hasło tymczasowe z „Dodaj użytkownika” (zdejmuje wymuszoną zmianę hasła), kolejne
# to rotacja. Procedura: docs/claude/podstawy/konto-e2e-na-produkcji.md
#
#   bash scripts/e2e_account_set_password.sh
#
# Działa tylko z sekretem repo: nowe hasło idzie wprost do `gh secret set`.
set -euo pipefail

API="${E2E_API_URL:-https://api.nexus.b2bnetwork.pl}"
REPO="${E2E_SECRET_REPO:-B2B-net-S-A/NEXUS}"
GH_SECRET_CMD="${E2E_GH_SECRET_CMD:-env -u GH_TOKEN gh secret set E2E_USER_PASSWORD --repo $REPO}"

read -r -p "Adres konta E2E: " email
read -r -s -p "Obecne hasło konta: " current
echo
new="$(openssl rand -hex 24)"

token="$(jq -n --arg e "$email" --arg p "$current" '{email:$e,password:$p}' \
  | curl -fsS -X POST "$API/api/auth/login" -H 'Content-Type: application/json' -d @- \
  | jq -r .access_token)"
[ -n "$token" ] && [ "$token" != "null" ] || { echo "Logowanie nie zwróciło tokenu." >&2; exit 1; }

jq -n --arg o "$current" --arg n "$new" '{current_password:$o,new_password:$n}' \
  | curl -fsS -o /dev/null -X POST "$API/api/auth/change-password" \
      -H "Authorization: Bearer $token" -H 'Content-Type: application/json' -d @-

printf '%s' "$new" | $GH_SECRET_CMD
echo "Hasło zmienione i zapisane w sekrecie E2E_USER_PASSWORD."
