/**
 * Pasek „wiele szans naraz” może zaznaczyć więcej, niż trasa przyjmuje w jednym
 * zapisie (lista do 2000, `MAX_IDS = 200` w `services/sales/bulk.py`). Front dzieli
 * zapis na paczki i oddaje jeden wynik.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { OPPORTUNITY_BULK_MAX_IDS, postOpportunityBulk } from "@/lib/api/sales";

vi.mock("@/lib/api", () => ({ api: { post: vi.fn() } }));

const apiPost = vi.mocked(api.post);
const range = (from: number, count: number) => Array.from({ length: count }, (_, index) => from + index);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("zapis wielu szans w paczkach", () => {
  it("trzyma limit trasy", () => {
    expect(OPPORTUNITY_BULK_MAX_IDS).toBe(200);
  });

  it("547 szans idzie w trzech zapisach po najwyżej 200, a wynik jest jeden", async () => {
    apiPost.mockImplementation(async (_url, body) => {
      const ids = (body as { ids: number[] }).ids;
      return { data: { done: ids.slice(1), skipped: [{ id: ids[0], title: null, reason: "szansa jest już zamknięta" }] } };
    });
    const ids = range(1, 547);
    const result = await postOpportunityBulk({ ids, action: "plan", days: 1 });
    const sent = apiPost.mock.calls.map((call) => (call[1] as { ids: number[] }).ids);
    expect(sent.map((chunk) => chunk.length)).toEqual([200, 200, 147]);
    expect(sent.flat()).toEqual(ids);
    expect(apiPost.mock.calls.every((call) => call[0] === "/api/sales/opportunities/bulk")).toBe(true);
    expect(apiPost.mock.calls[2][1]).toMatchObject({ action: "plan", days: 1 });
    expect(result.done).toHaveLength(544);
    expect(result.skipped.map((skip) => skip.id)).toEqual([1, 201, 401]);
  });

  it("do 200 szans to jeden zapis", async () => {
    apiPost.mockResolvedValue({ data: { done: [5, 6], skipped: [] } });
    await expect(postOpportunityBulk({ ids: [5, 6], action: "owner", owner_user_id: 9 })).resolves.toEqual({
      done: [5, 6],
      skipped: [],
    });
    expect(apiPost).toHaveBeenCalledTimes(1);
  });

  it("błąd pierwszej paczki to błąd całego zapisu, bo nic się nie zapisało", async () => {
    apiPost.mockRejectedValue(new Error("boom"));
    await expect(postOpportunityBulk({ ids: range(1, 300), action: "close" })).rejects.toThrow("boom");
    expect(apiPost).toHaveBeenCalledTimes(1);
  });

  it("błąd późniejszej paczki: zapisane zostają, reszta wraca jako pominięta z powodem", async () => {
    apiPost
      .mockResolvedValueOnce({ data: { done: range(1, 200), skipped: [] } })
      .mockRejectedValueOnce({ response: { status: 500, data: { detail: "Błąd serwera" } } });
    const result = await postOpportunityBulk({ ids: range(1, 450), action: "close" });
    expect(apiPost).toHaveBeenCalledTimes(2);
    expect(result.done).toHaveLength(200);
    expect(result.skipped.map((skip) => skip.id)).toEqual(range(201, 250));
    expect(result.skipped[0].reason).toMatch(/^nie zapisano/);
  });
});
