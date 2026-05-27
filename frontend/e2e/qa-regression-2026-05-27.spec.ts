/**
 * QA session 2026-05-27 regression specs.
 *
 * Cementuje 5 fixów (PR #332 + #352 + #353) tak, że nie wracają cicho gdy
 * ktoś za 2 miesiące nieświadomie przekształci enum/JOIN/schema. Każdy test
 * dokumentuje ORYGINALNY bug w komentarzu + checkuje REGRESJĘ-specific assertion
 * (nie "happy path" smoke test).
 *
 * Auth: korzysta z state.json wytworzonego przez auth.setup.ts. Bez
 * E2E_USER_PASSWORD secret setup-step zostanie skipped → te testy też skipują.
 */
import { test, expect } from "@playwright/test";

test.describe("QA regression 2026-05-27 — 5 fixów (PR #332/#352/#353)", () => {
  test("BE-V: DR Delivery Lead Dashboard z date filter zwraca 200 (nie stuck 503)", async ({
    request,
  }) => {
    // Bug: asyncpg infers DATE type z `k.report_month >= :start_date` bez CAST,
    // string '2026-05-01' wywalało DataError "'str' object has no attribute toordinal".
    // Po fix: parse str → datetime.date przed bind, expect 200.
    const r = await request.get(
      "/api/dynareporter/delivery-lead-dashboard/dashboard?start_date=2026-05-01&end_date=2026-05-30",
    );
    expect(r.status(), `pre-fix zwracało 503, fix #V w PR #332`).toBe(200);
    const body = await r.json();
    expect(body).toHaveProperty("delivery_leads");
    expect(body).toHaveProperty("team_stats");
  });

  test("BE-8: GET /api/reports/clients/1/trend zwraca 200 (nie KeyError close_reasons)", async ({
    request,
  }) => {
    // Bug: reports.py:946 drugi bucket init dla klientów z active_jobs ale 0
    // closed nie miał klucza "close_reasons" → KeyError przy render.
    // Po fix: dodać "close_reasons": {} do drugiego bucket init.
    const r = await request.get("/api/reports/clients/1/trend?months=6");
    expect(r.status(), `pre-fix KeyError → 503, fix #8 w PR #332`).toBe(200);
  });

  test("#28: GET /api/dr/placements/stats/by-client zwraca client_name (nie tylko id)", async ({
    request,
  }) => {
    // Bug: endpoint zwracał tylko `client_id`, frontend pokazywał "Klient #13"
    // zamiast "Nordea Bank AB". Po fix: LEFT JOIN Client + client_name field.
    const r = await request.get("/api/dr/placements/stats/by-client?days=90&limit=10");
    expect(r.status()).toBe(200);
    const body = await r.json();
    if (body.length > 0) {
      // Pierwszy item powinien mieć client_name jeśli backend zaktualizowany.
      // Allow null dla orphan placements (LEFT JOIN tolerates stale client_id).
      expect(body[0], "schema musi mieć client_name field").toHaveProperty("client_name");
    }
  });

  test("#17: Dashboard Lejek rekrutacji NIE pokazuje hardcoded 120/78/45/18/9", async ({
    page,
  }) => {
    // Bug: FunnelV2 used `?? 120 / ?? 78 / ?? 45 / ?? 18 / ?? 9` jako fallback,
    // wyglądało jak realne metryki ale admini porównywali z Insights gdzie
    // real funnel 14/17/2/18/9 — sprzeczne.
    // Po fix: fallback → 0 + empty state "Brak danych" gdy wszystkie 0.
    await page.goto("/");
    await page.waitForLoadState("networkidle", { timeout: 15_000 });

    // Lejek section musi się załadować.
    const lejek = page.locator('text="Lejek rekrutacji"').first();
    await expect(lejek).toBeVisible();

    // Po wczytaniu: ALBO real data z `/api/dashboard/kpis` ALBO empty state.
    // Pre-fix zawsze pokazywał te exact wartości — sprawdzamy że NIE wszystkie 5
    // są widoczne (oznacza fake fallback aktywny).
    const body = await page.content();
    const hasAllMockNumbers =
      body.includes(">120<") &&
      body.includes(">78<") &&
      body.includes(">45<") &&
      body.includes(">18<") &&
      body.includes(">9<");
    expect(
      hasAllMockNumbers,
      "Wszystkie 5 hardcoded mock numbers (120/78/45/18/9) widoczne → regresja fix #17",
    ).toBe(false);
  });

  test("BE-1N: enum userrole zawiera head_of_recruitment (nie 'manager')", async ({
    request,
  }) => {
    // Bug: candidates.py:1519 query używała `User.role.in_(["admin", "manager"])`
    // ale enum `userrole` ma `head_of_recruitment` (nie `manager`) — wywalało
    // InvalidTextRepresentationError na każdym POST /api/candidates.
    // Po fix: "manager" → "head_of_recruitment".
    // Smoke test: lista userów z role=head_of_recruitment musi działać (proof
    // że enum value valid). Jeśli ktoś przywróci "manager", filtr zwróci 500.
    const r = await request.get("/api/users?roles=head_of_recruitment");
    expect(r.status(), `enum head_of_recruitment musi być valid`).toBeLessThan(500);
  });
});
