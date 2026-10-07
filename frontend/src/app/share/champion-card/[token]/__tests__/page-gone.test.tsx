/**
 * D2 (0424, 07.10.2026): karta Championa dla klienta wycofana. Serwer odpowiada
 * na stare linki 410 — strona mówi „link nieważny”, a nie „spróbuj ponownie”
 * (chwilowa awaria) ani ogólne 404 aplikacji.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/server-forwarded", () => ({
  forwardedClientHeaders: async () => ({}),
}));

import PublicChampionCardPage from "../page";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("karta Championa — wycofany link (410)", () => {
  it("410 renderuje „Link nieprawidłowy lub wygasł”", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Link wycofany" }), { status: 410 })),
    );
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(await PublicChampionCardPage({ params: Promise.resolve({ token: "staryToken" }) }));
    expect(screen.getByRole("alert")).toHaveTextContent("Link nieprawidłowy lub wygasł");
    expect(screen.queryByText("Nie udało się otworzyć linku")).toBeNull();
  });
});
