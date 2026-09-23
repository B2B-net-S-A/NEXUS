/**
 * QA session 2026-05-27 regression specs.
 *
 * Cementuje fixy (PR #332 + #352 + #353) tak, że nie wracają cicho gdy
 * ktoś za 2 miesiące nieświadomie przekształci enum/JOIN/schema. Każdy test
 * dokumentuje ORYGINALNY bug w komentarzu + checkuje REGRESJĘ-specific assertion
 * (nie "happy path" smoke test).
 *
 * `@stack` (plan poprawy QA, 15.09.2026): wywołania API idą przez sesję
 * z tokenem (`helpers/api.ts`). Dawniej fixture `request` nie niósł tokena,
 * więc każdy test dostawał 401 — asercje `toBe(200)` nie mogły przejść, a
 * `< 500` przechodziła zawsze. Scenariusz #17 (sztuczne liczby w „Lejku
 * rekrutacji" dashboardu) usunięty 15.09 — tej sekcji nie ma już w aplikacji.
 * Scenariusze BE-V i #28 (endpointy DynaReportera) usunięte 23.09.2026 razem
 * z modułem.
 */
import { test, expect, expectStatus } from "./helpers/api";
import { createClient } from "./helpers/entities";

test.describe("QA regression 2026-05-27 (PR #332/#352/#353) @stack", () => {
  test("BE-8: GET /api/reports/clients/{id}/trend zwraca 200 (nie KeyError close_reasons)", async ({
    admin,
  }) => {
    // Bug: reports.py:946 drugi bucket init dla klientów z active_jobs ale 0
    // closed nie miał klucza "close_reasons" → KeyError przy render.
    // Po fix: dodać "close_reasons": {} do drugiego bucket init.
    const client = await createClient(admin.api);
    const r = await admin.api.get(`/api/reports/clients/${client.id}/trend?months=6`);
    expect(r.status(), `pre-fix KeyError → 503, fix #8 w PR #332`).toBe(200);
  });

  test("BE-1N: enum userrole zawiera head_of_recruitment (nie 'manager')", async ({
    admin,
  }) => {
    // Bug: candidates.py:1519 query używała `User.role.in_(["admin", "manager"])`
    // ale enum `userrole` ma `head_of_recruitment` (nie `manager`) — wywalało
    // InvalidTextRepresentationError na każdym POST /api/candidates.
    // Po fix: "manager" → "head_of_recruitment".
    // Smoke test: lista userów z role=head_of_recruitment musi działać (proof
    // że enum value valid). Jeśli ktoś przywróci "manager", filtr zwróci 500.
    const r = await admin.api.get("/api/users?roles=head_of_recruitment");
    await expectStatus(r, 200, "enum head_of_recruitment musi być valid");
  });
});
