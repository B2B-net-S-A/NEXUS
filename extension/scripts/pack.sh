#!/bin/sh
# ZIP do Chrome Web Store: tylko to, czego potrzebuje przeglądarka
# (manifest, ikony, src). Bez testów, fixture'ów, node_modules i dokumentacji.
# Użycie (z katalogu extension/ albo skądkolwiek): sh scripts/pack.sh
set -eu

cd "$(dirname "$0")/.."
VERSION=$(node -p "require('./manifest.json').version")
mkdir -p dist
OUT="dist/nexus-linkedin-${VERSION}.zip"
rm -f "$OUT"

# Sprawdzenie przed pakowaniem: poprawny JSON i zielone testy.
node -e "JSON.parse(require('fs').readFileSync('manifest.json','utf8'))"
if [ -d node_modules/linkedom ]; then
  node --test test
else
  echo "Brak zależności testów. Uruchom npm ci w extension/ przed pakowaniem." >&2
  exit 1
fi

zip -r -X -q "$OUT" manifest.json icons src -x "*.DS_Store"
unzip -t "$OUT" >/dev/null
shasum -a 256 "$OUT" > "$OUT.sha256"
echo "Gotowe: extension/$OUT"
unzip -l "$OUT" | tail -n 1
