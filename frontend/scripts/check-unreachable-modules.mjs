#!/usr/bin/env node
/**
 * Bramka nieosiągalnych modułów.
 *
 * Po co: usunięcie ostatniego miejsca montowania komponentu NIE psuje builda —
 * komponent dalej się kompiluje, bo importuje go jeszcze jego własny test, więc
 * CI zostaje zielone, a funkcja po cichu znika z produktu. Dokładnie to zdarzyło
 * się 2026-08-04 (`6ddbfd4c`, #1031): przepisanie dashboardów osierociło
 * `ContactOversightPanel` (nadzór nad kolejką pierwszego kontaktu dla Head of
 * Recruitment) i nikt nie zauważył przez 16 dni. Martwy komponent i skasowana
 * funkcja są w diffie NIE DO ODRÓŻNIENIA.
 *
 * Co robi: liczy domknięcie grafu importów od wejść App Routera i wypisuje
 * pliki źródłowe, do których nie da się dojść. Zna BASELINE (niżej) — pliki
 * dziś nieosiągalne, których usunięcie wymaga decyzji produktowej. Nowy sierota
 * = wyjście 1.
 *
 * Świadome ograniczenia (bramka ma być cicha, nie sprytna):
 *  - importy dynamiczne ze ZMIENNĄ ścieżką są niewidoczne. Repo ich nie używa;
 *    gdyby zaczęło — dopisz plik do BASELINE z komentarzem, zamiast rozbudowywać
 *    parser o zgadywanie.
 *  - testy nie są ani wejściem, ani wynikiem: test importujący martwy plik to
 *    właśnie ta zieleń, która niczego nie dowodzi.
 *
 * Uruchomienie: `node scripts/check-unreachable-modules.mjs` (zero zależności).
 */

import { readdirSync, readFileSync, statSync } from "node:fs"
import { dirname, extname, join, relative, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const FRONTEND_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const SRC = join(FRONTEND_ROOT, "src")

/** Pliki, które Next traktuje jako wejście trasy (reszta w `app/` to zwykłe moduły). */
const ROUTE_FILES = new Set([
  "page",
  "layout",
  "route",
  "loading",
  "error",
  "not-found",
  "template",
  "default",
  "global-error",
  "sitemap",
  "robots",
  "manifest",
  "opengraph-image",
  "icon",
  "apple-icon",
])

const SOURCE_EXT = [".tsx", ".ts", ".jsx", ".js"]

/**
 * Katalogi celowo trzymane jako BIBLIOTEKA — nieużywany prymityw nie jest
 * sierotą po funkcji, tylko klockiem czekającym na użycie (`components/ui/*`
 * to rejestr shadcn: zob. `frontend/docs/ds/ADDING-BLOCKS.md`).
 */
const LIBRARY_PREFIXES = ["components/ui/"]

/**
 * Wejścia spoza App Routera, o których Next/Vitest wie, a graf importów nie.
 */
const EXTRA_ENTRIES = new Set([
  "instrumentation.ts", // Next.js — inicjalizacja Sentry po stronie serwera
  "test/setup.ts", // vitest.config.ts → setupFiles
])

/**
 * Pliki nieosiągalne ŚWIADOMIE — zdjęcie ich wymaga decyzji spoza refaktoru.
 * Skracanie tej listy jest mile widziane; dopisywanie do niej wymaga zdania
 * wyjaśniającego, na co dany plik czeka. Lista jest tu po to, żeby dług był
 * NAZWANY: dopóki siedzi w baseline, kolejny rename go nie „zaktualizuje"
 * w przekonaniu, że dotyka żywej powierzchni.
 */
const BASELINE = new Set([
  // Moduł poczty (4 pliki): kompletna powierzchnia bez trasy. Do włączenia albo
  // do usunięcia razem z decyzją, czy NEXUS ma własnego klienta mailowego.
  "components/emails/EmailBulkActionBar.tsx",
  "components/emails/EmailCompose.tsx",
  "components/emails/EmailThreadList.tsx",
  "components/emails/EmailThreadView.tsx",
  "lib/email-threading.ts",
  // Stary dashboard Delivery Leada: `app/dashboard/delivery-lead/page.tsx` to
  // dziś samo przekierowanie na `/dashboard?preset=delivery-lead`, więc cały
  // katalog `_components` jest martwy. Usuwać osobną partią (13 plików).
  "app/dashboard/delivery-lead/_components/DeliveryTabs.tsx",
  "app/dashboard/delivery-lead/_components/DlClientsTable.tsx",
  "app/dashboard/delivery-lead/_components/DlHeader.tsx",
  "app/dashboard/delivery-lead/_components/DlKpiRow.tsx",
  "app/dashboard/delivery-lead/_components/DlRanking.tsx",
  "app/dashboard/delivery-lead/_components/DlTrendChart.tsx",
  "app/dashboard/delivery-lead/_components/PastelKpi.tsx",
  "app/dashboard/delivery-lead/_components/PendingVerificationsWidget.tsx",
  "app/dashboard/delivery-lead/_components/tabs/ActiveJobsTab.tsx",
  "app/dashboard/delivery-lead/_components/tabs/MyClientsTab.tsx",
  "app/dashboard/delivery-lead/_components/tabs/MyTeamTab.tsx",
  "app/dashboard/delivery-lead/_components/types.ts",
  // DynaReporter jest wygaszany — nie sprzątamy tu nic, dopóki nie zapadnie
  // decyzja o `DYNAREPORTER_MODE=off` i usunięciu modułu.
  "app/dynareporter/admin-dashboard/_modules/DataHistoryView.tsx",
  // CloudTalk: integracja świadomie zneutralizowana (decyzja 28.07 — koszt),
  // karta zdjęta z Ustawień, komponent zachowany jako punkt zaczepienia pod
  // następną telefonię. Patrz CLAUDE.md → sekcja CloudTalk.
  "components/settings/CloudTalkSettingsCard.tsx",
  "components/dashboard/CallStatsWidget.tsx",
  // Zakładka powiadomień profilu klienta — odmontowana, nie zweryfikowano czy
  // świadomie; wymaga sprawdzenia z produktem przed usunięciem.
  "app/clients/[id]/NotificationsTab.tsx",
])

function walk(dir) {
  const out = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith(".")) continue
    const full = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...walk(full))
    else if (SOURCE_EXT.includes(extname(entry.name))) out.push(full)
  }
  return out
}

const isTest = (file) =>
  file.includes(`${"/"}__tests__${"/"}`) ||
  /\.(test|spec)\.[jt]sx?$/.test(file) ||
  file.endsWith(".d.ts")

function isRouteEntry(file) {
  const rel = relative(SRC, file)
  if (rel === "middleware.ts" || rel === "middleware.tsx") return true
  if (EXTRA_ENTRIES.has(rel)) return true
  if (!rel.startsWith("app/")) return false
  const base = rel.split("/").pop().replace(/\.[jt]sx?$/, "")
  return ROUTE_FILES.has(base)
}

/**
 * Specyfikatory importu z pliku — statyczne, `import()` i `require()`.
 *
 * Świadomie prosto i szeroko, zamiast parsować składnię: wzorzec dopasowujący
 * całe zdanie `import ... from "..."` gubi importy wieloliniowe i te bez spacji
 * przed cudzysłowem (`from"@/..."` naprawdę występuje w repo) — a KAŻDA
 * zgubiona krawędź to fałszywy alarm o martwym pliku, czyli dokładnie to, co
 * uczy ignorować tę bramkę. Ewentualne trafienie w napis z komentarza tylko
 * dokłada krawędź, więc najgorszym skutkiem jest pominięcie sieroty.
 */
function specifiers(source) {
  const found = []
  const patterns = [
    /\bfrom\s*["']([^"']+)["']/g,
    /\bimport\s*\(\s*["']([^"']+)["']/g,
    /\brequire\s*\(\s*["']([^"']+)["']/g,
    /\bimport\s+["']([^"']+)["']/g,
  ]
  for (const re of patterns) {
    let m
    while ((m = re.exec(source)) !== null) found.push(m[1])
  }
  return found
}

function resolveSpecifier(spec, fromFile) {
  let base
  if (spec.startsWith("@/")) base = join(SRC, spec.slice(2))
  else if (spec.startsWith(".")) base = resolve(dirname(fromFile), spec)
  else return null // pakiet z node_modules

  const candidates = [
    base,
    ...SOURCE_EXT.map((ext) => base + ext),
    ...SOURCE_EXT.map((ext) => join(base, "index" + ext)),
  ]
  for (const candidate of candidates) {
    try {
      if (statSync(candidate).isFile()) return candidate
    } catch {
      /* nie istnieje — próbuj dalej */
    }
  }
  return null
}

const allFiles = walk(SRC)
const roots = allFiles.filter((f) => isRouteEntry(f))
const reachable = new Set()
const queue = [...roots]

while (queue.length) {
  const file = queue.pop()
  if (reachable.has(file)) continue
  reachable.add(file)
  let source
  try {
    source = readFileSync(file, "utf8")
  } catch {
    continue
  }
  for (const spec of specifiers(source)) {
    const target = resolveSpecifier(spec, file)
    if (target && !reachable.has(target)) queue.push(target)
  }
}

const orphans = allFiles
  .filter((f) => !reachable.has(f) && !isTest(f) && !isRouteEntry(f))
  .map((f) => relative(SRC, f))
  .filter((rel) => !LIBRARY_PREFIXES.some((prefix) => rel.startsWith(prefix)))
  .sort()

const unexpected = orphans.filter((f) => !BASELINE.has(f))
const staleBaseline = [...BASELINE].filter((f) => !orphans.includes(f)).sort()

if (staleBaseline.length) {
  console.log(
    "BASELINE do przycięcia (te pliki są już osiągalne albo nie istnieją):\n" +
      staleBaseline.map((f) => `  - ${f}`).join("\n")
  )
}

if (unexpected.length) {
  console.error(
    `\nNieosiągalne z żadnej trasy (${unexpected.length}):\n` +
      unexpected.map((f) => `  - ${f}`).join("\n") +
      "\n\nAlbo zamontuj je z powrotem (jeśli to funkcja, która miała zostać), " +
      "albo usuń razem z ich testami, albo dopisz do BASELINE w " +
      "scripts/check-unreachable-modules.mjs z uzasadnieniem.\n"
  )
  process.exit(1)
}

console.log(
  `OK — 0 nowych nieosiągalnych modułów (${reachable.size} osiągalnych, ` +
    `${BASELINE.size} w baseline).`
)
