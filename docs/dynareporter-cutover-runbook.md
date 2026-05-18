# DynaReporter cutover runbook (Faza B.3)

> Operacyjne kroki cutoveru z Coolify standalone (reports.dynaminds.pl) na
> Nexus monorepo (nexus.dynaminds.pl/dynareporter/*).
>
> **Pre-req:** wszystkie PR-y B.0-B.2 zmergowane i zdeployowane na prod.
> ETL `--apply` uruchomiony (74 users zmigrowani, 57 tabel dr_* mają dane).

## Krok 1 — Smoke test pełnego stacku

Najpierw potwierdź że wszystko działa po stronie Nexusa zanim DNS zmienimy.

```bash
# Healthcheck nexus
SHORT_SHA=$(git rev-parse --short=7 origin/main)
UA="dynaminds-smoke-test/1.0 (+manual; Nexus-cutover)"
curl -fsSL -A "$UA" "https://nexus.dynaminds.pl/api/health" | jq

# DynaReporter endpoints sanity
for ep in profile/me kpi/body-leasing/summary kpi/sales/summary kpi/delivery-lead/summary placements/my clients-mrr/summary competitions/podium przetargi/project-summary board/latest sales-mgmt/projects; do
  echo "=== $ep ==="
  curl -sIL -A "$UA" -H "Authorization: Bearer $JWT_TOKEN" \
    "https://nexus.dynaminds.pl/api/dynareporter/$ep" | head -3
done
```

## Krok 2 — Chrome MCP E2E smoke

Sprawdź każdy z 11 modułów przez Chrome MCP:

1. Login na nexus.dynaminds.pl (Artur admin → ma wszystkie sections)
2. Sidebar → "Raporty KPI" → `/dynareporter`
3. Klikaj każdą kartkę modułu:
   - body-leasing → wykres trendu + Liga Mistrzów top-10
   - sales → win-rate widget
   - delivery-lead → fill-rate + 12-mc table
   - placements → 2 ranking widgets
   - clients-mrr → 3 KPI cards + 2 tabele
   - competitions → podium z medalami
   - przetargi → P&L per project
   - board → 8 KPI cards + 12-mc history
   - sales-mgmt → 4 KPI cards + 2 listy
   - mindy → commentary + chat (powinien działać jeśli ANTHROPIC_API_KEY)
   - admin/upload → upload XLSX + history
4. Porównaj wartości z `reports.dynaminds.pl` — data parity check

## Krok 3 — DNS CNAME (Cloudflare)

**Operacja nieodwracalna** w kontekście user expectations — sprawdź po
sukcesie kroku 2.

Via CF dashboard (https://dash.cloudflare.com → dynaminds.pl → DNS):

1. Znajdź rekord A `reports.dynaminds.pl → 91.99.199.112`
2. **Edit** → zmień typ na **CNAME** → wartość: `nexus.dynaminds.pl`
3. Proxy: **ON** (orange cloud)
4. Save

Lub przez Cloudflare API (z X-Atok approach z memory):

```js
// W konsoli CF dashboard
(async () => {
  const ZONE = 'f394bce89fa6bf50fb4a03ecc472e18c';
  const atok = JSON.parse(localStorage.getItem('bootstrap-cache')).atok;
  // Najpierw delete starego A
  const a = await fetch(`/api/v4/zones/${ZONE}/dns_records?name=reports.dynaminds.pl&type=A`, {
    headers: {'X-Atok': atok, 'X-Cross-Site-Security': 'dash'},
    credentials: 'include'
  }).then(r => r.json());
  for (const rec of a.result) {
    await fetch(`/api/v4/zones/${ZONE}/dns_records/${rec.id}`, {
      method: 'DELETE',
      headers: {'X-Atok': atok, 'X-Cross-Site-Security': 'dash'},
      credentials: 'include'
    });
  }
  // Create CNAME
  await fetch(`/api/v4/zones/${ZONE}/dns_records`, {
    method: 'POST',
    headers: {'X-Atok': atok, 'X-Cross-Site-Security': 'dash', 'Content-Type': 'application/json'},
    credentials: 'include',
    body: JSON.stringify({
      type: 'CNAME', name: 'reports', content: 'nexus.dynaminds.pl',
      ttl: 1, proxied: true,
      comment: 'DynaReporter migrated to Nexus (B.3 cutover 2026-05-18)'
    })
  });
})();
```

Propagacja: 1-5 min via CF (proxy on accelerates).

## Krok 4 — Weryfikacja DNS

```bash
dig +short reports.dynaminds.pl
# powinno zwrócić CF IP (104.21.* lub 172.67.*) — TAK SAMO jak nexus.dynaminds.pl

curl -sI https://reports.dynaminds.pl/dynareporter/profile | head -5
# expect: HTTP/2 200 + content-type text/html (Nexus serves /dynareporter)
```

## Krok 5 — Czekamy 24-48h (observation window)

W tym czasie Coolify standalone (`wpal3b75siiiu8lzw8ccg7ad`) NADAL DZIAŁA
na server 91.99.199.112 ale ma inny CNAME (jeśli ktoś używał starego URL
przez bookmark → trafia na nexus). Standalone jest backup'em.

## Krok 6 (B.4) — Coolify standalone shutdown

Po 24-48h observation, gdy nikt nie zgłasza problemów:

```bash
TOKEN="<bearer>"  # z previous Coolify token generation
APP_UUID="wpal3b75siiiu8lzw8ccg7ad"
COOLIFY_URL="https://coolify-nexus.dynaminds.pl"

# Stop containers (zachowuje volume + obraz, można odtworzyć)
curl -X GET -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" \
  "$COOLIFY_URL/api/v1/applications/$APP_UUID/stop"

# Lub via Coolify UI: Resources → dynareporter → Stop
```

**NIE delete** appki — zostaw stopped. Volume `dynareporter_pgdata`
zostaje na dysku, gdyby trzeba było odtworzyć szybko.

**Render — zostaje per user request.** Nie ruszać Render web service ani
DB.

## Krok 7 — Update memory

Memory entry `~/.claude/projects/.../project_dynareporter_migration.md`:
mark **Faza B done 2026-05-18** (full migration: B.0 + B.1 + 11 modułów
B.2 + B.3 cutover).

## Rollback (jeśli coś pójdzie nie tak)

W kroku 3 (DNS): cofnij CNAME → A `reports.dynaminds.pl → 91.99.199.112`.
Coolify standalone nadal działa, serwuje stare reports.dynaminds.pl.

W kroku 6 (decommission): jeśli już zatrzymane, w Coolify UI: Resources
→ dynareporter → Start. Wraca w 1-2 min.

Render zostaje zawsze jako last-resort fallback.
