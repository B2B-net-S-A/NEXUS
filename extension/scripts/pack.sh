#!/bin/sh
# Dwie paczki z tych samych plików (manifest, ikony, src) — bez testów,
# fixture'ów, node_modules i dokumentacji:
#
# 1. Zespół (instalacja z ZIP-a, „Wczytaj rozpakowane”):
#    frontend/public/wtyczka/nexus-linkedin.zip — z polem `key` w manifeście,
#    więc wtyczka ma na każdym laptopie to samo id (pmnon…, lista
#    LINKEDIN_EXTENSION_IDS). Bez `key` id zależy od ścieżki katalogu i NEXUS
#    odmówiłby połączenia. Plik jest w repo i pobiera się go z NEXUSA (/wtyczka);
#    test `team-zip.test.mjs` pilnuje, że jest zgodny ze źródłami.
# 2. Chrome Web Store: extension/dist/nexus-linkedin-<wersja>-webstore.zip —
#    BEZ `key` (sklep nadaje własne id i nie przyjmuje tego pola).
#
# Użycie (z katalogu extension/ albo skądkolwiek): sh scripts/pack.sh
set -eu

cd "$(dirname "$0")/.."
VERSION=$(node -p "require('./manifest.json').version")

# Sprawdzenie przed pakowaniem: poprawny JSON i zielone testy (bez testu
# zgodności ZIP-a zespołu — ten ZIP właśnie powstaje).
node -e "JSON.parse(require('fs').readFileSync('manifest.json','utf8'))"
if [ ! -d node_modules/linkedom ]; then
  echo "Brak zależności testów. Uruchom npm ci w extension/ przed pakowaniem." >&2
  exit 1
fi
SKIP_TEAM_ZIP_CHECK=1 node --test test

# Pliki w ZIP-ie ze stałą datą — ten sam kod daje ten sam ZIP (mniejszy diff w repo).
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
cp -R manifest.json icons src "$STAGE/"
find "$STAGE" -name .DS_Store -delete
find "$STAGE" -exec touch -t 202601010000 {} +

TEAM_DIR=../frontend/public/wtyczka
TEAM="$TEAM_DIR/nexus-linkedin.zip"
mkdir -p "$TEAM_DIR"
rm -f "$TEAM"
(cd "$STAGE" && find manifest.json icons src -type f | LC_ALL=C sort | zip -X -q -@ "$OLDPWD/$TEAM")
unzip -t "$TEAM" >/dev/null
echo "Zespół:    frontend/public/wtyczka/nexus-linkedin.zip ($VERSION)"

mkdir -p dist
STORE="dist/nexus-linkedin-${VERSION}-webstore.zip"
rm -f "$STORE"
node -e "
const fs = require('fs');
const p = process.argv[1];
const m = JSON.parse(fs.readFileSync(p, 'utf8'));
delete m.key;
fs.writeFileSync(p, JSON.stringify(m, null, 2) + '\n');
" "$STAGE/manifest.json"
touch -t 202601010000 "$STAGE/manifest.json"
(cd "$STAGE" && find manifest.json icons src -type f | LC_ALL=C sort | zip -X -q -@ "$OLDPWD/$STORE")
unzip -t "$STORE" >/dev/null
shasum -a 256 "$STORE" > "$STORE.sha256"
echo "Web Store: extension/$STORE"
