/**
 * E2E flow: kontrakt draft lifecycle — create → edit draft → render → finalize.
 *
 * Pokrywa 3 stubs z `flow-stubs-todo.spec.ts`:
 * - P0 create contract draft → Tiptap edit → finalize
 * - P0 render contract PDF preview (UWAGA: response = text/html, nie application/pdf)
 * - P1 send contract via Autenti (assertion na DEFAULT state AUTENTI_ENABLED=false → 503)
 *
 * Kluczowe gotcha (per backend research 2026-05-28):
 * - render endpoint: `/api/contracts/{id}/draft/render-pdf` (NIE `/render-pdf`)
 * - finalize endpoint: `/api/contracts/{id}/draft/finalize` (NIE `/finalize`)
 * - finalize wymaga: start_date + end_date + rate_candidate + rate_client +
 *   contract_type + work_mode wszystkie non-null (validate_ready_for_activation)
 * - finalize: status flow DRAFT → ACTIVE (direct, brak finalize_pending)
 * - Autenti default disabled na prod → 503 z message "AUTENTI_ENABLED=false"
 *
 * Cleanup: DELETE candidate + contract (po finalize DELETE wciąż działa, brak gate).
 */
import { test, expect } from "@playwright/test";
import { EntityTracker, uniqueName, E2E_PREFIX } from "./helpers/test-entities";

const tracker = new EntityTracker();

test.afterEach(async ({ request }) => {
  const { deleted, failed } = await tracker.cleanup(request);
  if (failed > 0) {
    console.warn(`[cleanup] ${deleted} deleted, ${failed} FAILED — possible orphan`);
  }
});

async function firstClientId(request: any): Promise<number | null> {
  const r = await request.get("/api/clients?limit=1");
  if (!r.ok()) return null;
  const data = await r.json();
  const list = Array.isArray(data) ? data : (data.items ?? data.results ?? []);
  return list[0]?.id ?? null;
}

test.describe("Flow: contract draft lifecycle", () => {
  test("create draft → PATCH content_html → render HTML → finalize → 503 from Autenti", async ({
    request,
  }) => {
    // 1. Stwórz test candidate (wymagany jako FK kontraktu)
    const candCreate = await request.post("/api/candidates", {
      data: {
        name: uniqueName("contract").split(" ")[0],
        lastname: "Draft",
        email: `qa-e2e-contract-${Date.now()}@test.local`,
        source: "manual",
        status: "active",
        availability_status: "unknown",
      },
    });
    expect([200, 201]).toContain(candCreate.status());
    const candidate = await candCreate.json();
    tracker.track("/api/candidates", candidate.id);

    // 2. Pobierz pierwszy istniejący client_id (nie tworzymy klienta — i tak
    // auto-assign test jest osobny spec).
    const clientId = await firstClientId(request);
    test.skip(clientId === null, "no clients in DB — skip contract flow");

    // 3. POST /api/contracts z wszystkimi polami wymaganymi przez
    // validate_ready_for_activation, żeby finalize nie zwrócił 409.
    const today = new Date();
    const startDate = today.toISOString().slice(0, 10);
    const endDate = new Date(today.getTime() + 90 * 24 * 60 * 60 * 1000)
      .toISOString()
      .slice(0, 10);

    const contractCreate = await request.post("/api/contracts", {
      data: {
        candidate_id: candidate.id,
        client_id: clientId,
        start_date: startDate,
        end_date: endDate,
        rate_candidate: 15000,
        rate_client: 20000,
        currency: "PLN",
        rate_unit: "monthly",
        contract_type: "b2b",
        work_mode: "remote",
      },
    });
    expect(contractCreate.status(), "contract create must succeed").toBe(201);
    const contract = await contractCreate.json();
    expect(contract.id).toBeTruthy();
    expect(contract.status).toBe("draft");
    tracker.track("/api/contracts", contract.id);

    // 4. PATCH /api/contracts/{id}/draft z content_html — bez tego render-pdf
    // zwróci 404 "Draft is empty".
    const draftHtml = `<h1>${E2E_PREFIX} Contract Draft</h1><p>Body leasing terms for testing.</p>`;
    const patchDraft = await request.patch(`/api/contracts/${contract.id}/draft`, {
      data: { content_html: draftHtml },
    });
    expect(patchDraft.status(), "PATCH draft must accept content_html").toBe(200);
    const draftBody = await patchDraft.json();
    expect(draftBody).toHaveProperty("content_html");

    // 5. GET render endpoint — pełna ścieżka `/draft/render-pdf`.
    // Response = text/html (NIE application/pdf — to "printable HTML" z
    // embedowanym window.print()).
    const render = await request.get(
      `/api/contracts/${contract.id}/draft/render-pdf`,
    );
    expect(render.status()).toBe(200);
    const contentType = render.headers()["content-type"] ?? "";
    expect(
      contentType.includes("text/html"),
      `render-pdf must be text/html (was: ${contentType})`,
    ).toBe(true);
    const renderBody = await render.text();
    expect(renderBody.length, "HTML body should be non-empty").toBeGreaterThan(100);

    // 6. POST finalize — direct DRAFT → ACTIVE (brak intermediate state).
    const finalize = await request.post(
      `/api/contracts/${contract.id}/draft/finalize`,
    );
    expect(finalize.status(), "finalize must succeed when all required fields set").toBe(
      200,
    );
    const finalizeBody = await finalize.json();
    expect(finalizeBody.contract_id).toBe(contract.id);
    expect(finalizeBody.status).toBe("active");
    expect(finalizeBody).toHaveProperty("document_id");

    // 7. POST /api/autenti/contracts/{id}/send — asercja na DEFAULT state
    // prod = AUTENTI_ENABLED=false → 503.
    // Jeśli kiedyś włączymy flag, zmień asercję na 202 (AutentiSendResponse).
    const autenti = await request.post(
      `/api/autenti/contracts/${contract.id}/send`,
      { data: {} },
    );
    if (autenti.status() === 503) {
      const detail = (await autenti.json()).detail ?? "";
      expect(
        detail.toLowerCase().includes("autenti"),
        `503 must mention Autenti (was: "${detail}")`,
      ).toBe(true);
    } else {
      // Flag jest włączony — sprawdź AutentiSendResponse shape.
      expect([200, 202]).toContain(autenti.status());
      const body = await autenti.json();
      expect(body).toHaveProperty("contract_id");
      expect(body.contract_id).toBe(contract.id);
    }

    // 8. Finalize idempotency — drugi POST powinien dać 409 (already active).
    const finalize2 = await request.post(
      `/api/contracts/${contract.id}/draft/finalize`,
    );
    expect(finalize2.status(), "finalize on active contract must return 409").toBe(409);
  });

  test("finalize na empty draft → 422 (validate_ready_for_activation gate)", async ({
    request,
  }) => {
    // 1. Stwórz candidate
    const candCreate = await request.post("/api/candidates", {
      data: {
        name: uniqueName("contract-empty").split(" ")[0],
        lastname: "Test",
        email: `qa-e2e-contract-empty-${Date.now()}@test.local`,
        source: "manual",
        status: "active",
        availability_status: "unknown",
      },
    });
    expect([200, 201]).toContain(candCreate.status());
    const candidate = await candCreate.json();
    tracker.track("/api/candidates", candidate.id);

    const clientId = await firstClientId(request);
    test.skip(clientId === null, "no clients in DB");

    // 2. POST contract bez optional fields — brak end_date/rates/work_mode.
    const start = new Date().toISOString().slice(0, 10);
    const contractCreate = await request.post("/api/contracts", {
      data: {
        candidate_id: candidate.id,
        client_id: clientId,
        start_date: start,
      },
    });
    expect(contractCreate.status()).toBe(201);
    const contract = await contractCreate.json();
    tracker.track("/api/contracts", contract.id);

    // 3. Bez PATCH-a draft (draft_content_html=null) — finalize zwróci 422.
    const finalize = await request.post(
      `/api/contracts/${contract.id}/draft/finalize`,
    );
    // 422 (empty draft) lub 409 (missing required fields) — oba prawidłowe gate'y.
    expect([409, 422]).toContain(finalize.status());
  });
});
