#!/usr/bin/env bash
# add-block.sh — pull UI building blocks into NEXUS safely (no config clobber).
#
#   ./scripts/add-block.sh primitive <name...>     # shadcn/ui atoms  -> src/components/ui/
#   ./scripts/add-block.sh shadcnblock <slug...>   # shadcnblocks ELITE -> src/components/blocks/
#
# Why not `npx shadcn add`? The CLI reformats tailwind.config.ts, remaps
# --sidebar -> --sidebar-background (which NEXUS does NOT define -> breaks the
# sidebar) and bumps existing dep versions. We fetch the registry JSON directly
# and write the file, so config + lockfile are never touched.
set -euo pipefail
cd "$(dirname "$0")/.."

RAW_COLOR_RE='gray-[0-9]|indigo-[0-9]|slate-[0-9]|zinc-[0-9]|neutral-[0-9]|bg-white|text-black|sidebar-background'

audit() {
  local f="$1"
  [ -f "$f" ] || { echo "  ✗ missing: $f"; return; }
  if grep -nE "$RAW_COLOR_RE" "$f" >/dev/null 2>&1; then
    echo "  ⚠ raw colors to rewrite -> tokens in $f (see docs/ds/ADDING-BLOCKS.md):"
    grep -nE "$RAW_COLOR_RE" "$f" | sed 's/^/      /'
  else
    echo "  ✓ token-clean: $f"
  fi
}

mode="${1:-}"; shift || true
case "$mode" in
  primitive)
    [ "$#" -gt 0 ] || { echo "usage: $0 primitive <name...>"; exit 1; }
    for n in "$@"; do
      tmp="$(mktemp)"
      code=$(curl -sL "https://ui.shadcn.com/r/styles/new-york/$n.json" -o "$tmp" -w '%{http_code}')
      [ "$code" = "200" ] || { echo "✗ $n: HTTP $code"; rm -f "$tmp"; continue; }
      python3 - "$tmp" <<'PY'
import json,sys,os
d=json.load(open(sys.argv[1]))
for f in d.get('files',[]):
    out=os.path.join('src/components/ui', os.path.basename(f['path']))
    open(out,'w').write(f['content']); print('wrote', out)
deps=d.get('dependencies') or []
if deps: print('  npm deps:', ' '.join(deps))
PY
      rm -f "$tmp"
      audit "src/components/ui/$n.tsx"
    done
    echo "→ install any new npm deps printed above: npm install <deps> --legacy-peer-deps"
    ;;
  shadcnblock)
    [ "$#" -gt 0 ] || { echo "usage: $0 shadcnblock <slug...>"; exit 1; }
    [ -f .env.local ] && { set -a; . ./.env.local; set +a; }
    : "${SHADCNBLOCKS_API_KEY:?SHADCNBLOCKS_API_KEY missing in .env.local}"
    if [ "$(date +%Y-%m-%d)" '>' "2026-08-21" ]; then
      echo "⚠ shadcnblocks key expired (2026-08-21) — regenerate at shadcnblocks.com/dashboard/api"
    fi
    mkdir -p src/components/blocks
    for slug in "$@"; do
      tmp="$(mktemp)"
      code=$(curl -sL -H "Authorization: Bearer $SHADCNBLOCKS_API_KEY" "https://www.shadcnblocks.com/r/$slug" -o "$tmp" -w '%{http_code}')
      [ "$code" = "200" ] || { echo "✗ $slug: HTTP $code"; rm -f "$tmp"; continue; }
      python3 - "$tmp" <<'PY'
import json,sys,os
d=json.load(open(sys.argv[1]))
for f in d.get('files',[]):
    out=os.path.join('src/components/blocks', os.path.basename(f['path']))
    open(out,'w').write(f['content']); print('wrote', out)
deps=d.get('dependencies') or []
if deps: print('  npm deps:', ' '.join(deps))
PY
      rm -f "$tmp"
      audit "src/components/blocks/$slug.tsx"
    done
    echo "→ rewrite flagged raw colors to tokens (docs/ds/ADDING-BLOCKS.md)"
    ;;
  *)
    echo "usage: $0 {primitive <name...>|shadcnblock <slug...>}"; exit 1 ;;
esac
