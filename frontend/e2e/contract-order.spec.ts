/**
 * Kontrakt ↔ zamówienie: uzupełnione zamówienie aktywuje szkic kontraktu
 * i przenosi na niego okres zamówienia (reguła synchronizacji z CLAUDE.md,
 * „Synchronizacja kontrakt ↔ zamówienia", migracja 0304).
 *
 * `@stack`. To jest przepływ, który audyt QA wymienił jako niepokryty
 * end-to-end: zamówienie → kontrakt → liczby widoczne w module.
 */
import { test, expect, jsonOf } from "./helpers/api";
import { createCandidate, createClient } from "./helpers/entities";

interface Contract {
  id: number;
  status: string;
  client_order_start_date: string | null;
  client_order_end_date: string | null;
  rate_unit: string;
}

function isoDay(offsetDays: number): string {
  const day = new Date();
  day.setUTCDate(day.getUTCDate() + offsetDays);
  return day.toISOString().slice(0, 10);
}

test.describe("Kontrakt i zamówienie @stack", () => {
  test("zamówienie z okresem i stawką przychodową aktywuje szkic kontraktu", async ({ admin }) => {
    const client = await createClient(admin.api);
    const candidate = await createCandidate(admin.api);
    const start = isoDay(-10);
    const end = isoDay(80);

    const draft = await jsonOf<Contract>(
      await admin.api.post("/api/contracts", {
        data: {
          candidate_id: candidate.id,
          client_id: client.id,
          contract_type: "b2b",
          start_date: start,
          rate_candidate: 120,
          rate_unit: "hourly",
        },
      }),
      201,
      "POST /api/contracts"
    );
    expect(draft.status).toBe("draft");

    await jsonOf<{ id: number }>(
      await admin.api.post(`/api/clients/${client.id}/orders`, {
        multipart: {
          contract_id: String(draft.id),
          title: `E2E-ZAM-${draft.id}`,
          order_type: "periodic",
          order_status: "active",
          start_date: start,
          end_date: end,
          rate_client: "160",
          rate_unit: "hourly",
        },
      }),
      201,
      "POST /api/clients/{id}/orders"
    );

    const synced = await jsonOf<Contract>(
      await admin.api.get(`/api/contracts/${draft.id}`),
      200,
      "GET /api/contracts/{id} po zapisie zamówienia"
    );
    expect(synced).toMatchObject({
      status: "active",
      client_order_start_date: start,
      client_order_end_date: end,
      rate_unit: "hourly",
    });
  });
});
