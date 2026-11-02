#!/usr/bin/env bash
# Staging na laptopie: backend i front z aktualnego origin/main, ta sama baza.
#
# Bez tego staging zostaje na kodzie z dnia ostatniego ręcznego builda
# (02.11.2026 miał kod z 22.10), a nocny Tester sprawdzałby stary kod.
# Dane kopiuje osobno `clone_from_hetzner.py`. Tu nic nie kasuje danych, a Postgres,
# S3 i Qdrant nie są restartowane. Migracje z maina wykonuje entrypoint backendu
# na bazie z STAGING_DATABASE_NAME.
#
# Użycie: scripts/staging/refresh_code.sh
# Kod wyjścia: 0 = staging na origin/main, 3 = kod nowy, schemat bazy nieaktualny.
set -euo pipefail

REPO="${NEXUS_REPO:-$HOME/NEXUS}"
CODE="${STAGING_CODE_DIR:-$HOME/.nexus-staging/code}"
ENV_FILE="${STAGING_ENV_FILE:-$HOME/.codex/worktrees/nexus-staging-data-promotion/.env.staging.local}"
API="http://localhost:8100"
FRONT="http://localhost:3100"

[ -f "$ENV_FILE" ] || { echo "Brak pliku $ENV_FILE (wzór: scripts/staging/env.staging.example)." >&2; exit 2; }

git -C "$REPO" fetch --quiet origin main
SHA="$(git -C "$REPO" rev-parse origin/main)"

running="$(curl -fsS --max-time 10 "$API/api/health" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' || true)"
if [ "$running" = "$SHA" ]; then
  echo "Staging już jest na $SHA."
  exit 0
fi

if [ -d "$CODE/.git" ] || [ -f "$CODE/.git" ]; then
  git -C "$CODE" checkout --quiet --detach "$SHA"
else
  mkdir -p "$(dirname "$CODE")"
  git -C "$REPO" worktree add --quiet --detach "$CODE" "$SHA"
fi
# `env_file` w compose czyta się względem katalogu projektu.
ln -sf "$ENV_FILE" "$CODE/.env.staging.local"

export GIT_SHA="$SHA"
BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export BUILT_AT
compose=(docker compose -p nexus-staging --project-directory "$CODE"
  -f "$CODE/docker-compose.staging.yml" --env-file "$ENV_FILE")

# Najpierw build: gdy padnie, stare kontenery działają dalej.
"${compose[@]}" build backend frontend
"${compose[@]}" up -d --no-deps --no-build backend frontend

# Pierwszy start po dłuższej przerwie wykonuje migracje, stąd długie okno.
for _ in $(seq 1 60); do
  now="$(curl -fsS --max-time 10 "$API/api/health" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)"
  if [ "$now" = "$SHA" ] && curl -fsS --max-time 10 -o /dev/null "$FRONT/login" 2>/dev/null; then
    # Kopia z rewizją, której main już nie zna, nie da się zmigrować, a health
    # i tak mówi „healthy”: nowy kod stoi wtedy na starym schemacie. Trzeba nowej kopii.
    migrations="$(curl -fsS --max-time 10 "$API/api/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["checks"].get("migrations",""))')"
    case "$migrations" in
      unhealthy*) echo "Staging na $SHA, ale schemat bazy jest nieaktualny: $migrations" >&2; exit 3 ;;
    esac
    echo "Staging na $SHA."
    exit 0
  fi
  sleep 15
done
echo "Staging nie odpowiedział wersją $SHA w 15 minut (API: ${now:-brak})." >&2
exit 1
