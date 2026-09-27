/**
 * Runda 10 (R10-N10-5): SSR karty Championa nie loguje tokenu linku.
 * Token w ścieżce to ważny dostęp do danych kandydata, a stdout kontenera
 * frontu trafia do Loki bez redakcji backendu.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/server-forwarded", () => ({
  forwardedClientHeaders: async () => ({}),
}));

import PublicChampionCardPage from "../page";

const TOKEN = "sekretnyTokenKarty123";

function loggedText(spy: { mock: { calls: unknown[][] } }): string {
  return JSON.stringify(spy.mock.calls.map((call) => call.map(String)));
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("karta Championa — log bez tokenu", () => {
  it.each([429, 503])("odpowiedź %s nie wpisuje tokenu do logu", async (status) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status })));
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    await PublicChampionCardPage({ params: Promise.resolve({ token: TOKEN }) });
    expect(spy).toHaveBeenCalled();
    expect(loggedText(spy)).not.toContain(TOKEN);
  });

  it("błąd sieci nie wpisuje tokenu do logu", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError(`fetch failed http://backend/api/public/champion-card/${TOKEN}`);
      }),
    );
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    await PublicChampionCardPage({ params: Promise.resolve({ token: TOKEN }) });
    expect(spy).toHaveBeenCalled();
    expect(loggedText(spy)).not.toContain(TOKEN);
  });
});
