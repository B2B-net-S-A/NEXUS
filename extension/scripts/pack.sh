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
# 3. Polityka Chrome z Intune (ExtensionInstallForcelist, decyzja Artura 29.10):
#    frontend/public/wtyczka/nexus-linkedin.crx + update.xml. Manifest jak
#    w ZIP-ie zespołu plus `update_url` na update.xml — z niego Chrome bierze
#    kolejne wersje. Podpis kluczem prywatnym do pola `key`
#    (NEXUS_EXTENSION_PEM, domyślnie ~/.config/nexus/linkedin-extension-team.pem
#    na laptopie Artura). Klucz nie trafia do repo ani do Actions: kto go ma,
#    wypchnie dowolny kod do każdego Chrome z polityką. Bez klucza ten krok
#    jest pomijany, a test `team-crx.test.mjs` pokaże, że .crx jest starszy.
#
# Użycie (z katalogu extension/ albo skądkolwiek): sh scripts/pack.sh
set -eu

TEAM_ID=pmnonjpommkjblgacmpaclgacjmipplm
TEAM_BASE_URL=https://nexus.b2bnetwork.pl/wtyczka
PEM=${NEXUS_EXTENSION_PEM:-$HOME/.config/nexus/linkedin-extension-team.pem}

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
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/stage"
mkdir "$STAGE"
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

# 3. CRX + update.xml dla polityki Chrome. Pakuje sam Chrome (format CRX3
# i podpis robi Google); scripts/crx3.mjs sprawdza wynik: podpis, id, ZIP.
if [ -f "$PEM" ]; then
  CHROME=${CHROME_BIN:-}
  if [ -z "$CHROME" ]; then
    for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" google-chrome chromium; do
      if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then CHROME=$c; break; fi
    done
  fi
  if [ -z "$CHROME" ]; then
    echo "Brak Chrome do spakowania .crx — ustaw CHROME_BIN." >&2
    exit 1
  fi
  CRXDIR="$WORK/nexus-linkedin"
  cp -R "$STAGE" "$CRXDIR"
  node -e "
const fs = require('fs');
const [p, url] = process.argv.slice(1);
const m = JSON.parse(fs.readFileSync(p, 'utf8'));
m.update_url = url;
fs.writeFileSync(p, JSON.stringify(m, null, 2) + '\n');
" "$CRXDIR/manifest.json" "$TEAM_BASE_URL/update.xml"
  find "$CRXDIR" -exec touch -t 202601010000 {} +
  # Chrome przyjmuje tylko PKCS#8: kopia w $WORK (0600), kasowana zaraz po
  # pakowaniu, a przy błędzie przez trap.
  (umask 077 && openssl pkcs8 -topk8 -nocrypt -in "$PEM" -out "$WORK/key.pem")
  # Osobny profil: bez niego polecenie trafia do otwartego Chrome i wraca od razu.
  "$CHROME" --pack-extension="$CRXDIR" --pack-extension-key="$WORK/key.pem" \
    --user-data-dir="$WORK/profile" --no-message-box >/dev/null 2>&1 || true
  rm -f "$WORK/key.pem"
  if [ ! -f "$WORK/nexus-linkedin.crx" ]; then
    echo "Chrome nie spakował .crx (zły klucz albo stara wersja Chrome)." >&2
    exit 1
  fi
  node scripts/crx3.mjs "$WORK/nexus-linkedin.crx" "$TEAM_ID"
  cp "$WORK/nexus-linkedin.crx" "$TEAM_DIR/nexus-linkedin.crx"
  MIN_CHROME=$(node -p "require('./manifest.json').minimum_chrome_version")
  cat > "$TEAM_DIR/update.xml" <<XML
<?xml version='1.0' encoding='UTF-8'?>
<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'>
  <app appid='$TEAM_ID'>
    <updatecheck codebase='$TEAM_BASE_URL/nexus-linkedin.crx' version='$VERSION' prodversionmin='$MIN_CHROME' />
  </app>
</gupdate>
XML
  echo "Intune:    frontend/public/wtyczka/nexus-linkedin.crx + update.xml ($VERSION)"
else
  echo "Intune:    pominięte — brak klucza $PEM (.crx i update.xml bez zmian)"
fi

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
