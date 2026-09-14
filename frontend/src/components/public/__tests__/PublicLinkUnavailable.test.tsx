import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/sign/[token]/SignForm", () => ({ default: () => null }));

import SignPage from "@/app/sign/[token]/page";
import PublicChampionCardPage from "@/app/share/champion-card/[token]/page";
import { publicLinkFailure } from "@/lib/public-link-state";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(status: number | "network") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      if (status === "network") throw new Error("ECONNREFUSED");
      return new Response(JSON.stringify({ detail: "x" }), { status });
    }),
  );
  vi.spyOn(console, "error").mockImplementation(() => {});
}

describe("publiczne linki: odmowa i awaria zamiast ogólnego 404 (UAT M12-B01)", () => {
  it("klasyfikuje 4xx jako nieprawidłowy link, 5xx i brak odpowiedzi jako awarię", () => {
    expect(publicLinkFailure(404)).toBe("invalid");
    expect(publicLinkFailure(410)).toBe("invalid");
    expect(publicLinkFailure(503)).toBe("unavailable");
    expect(publicLinkFailure(null)).toBe("unavailable");
  });

  it.each([
    ["podpis", SignPage],
    ["karta Championa", PublicChampionCardPage],
  ])("%s: nieznany token → „Link nieprawidłowy lub wygasł”", async (_name, Page) => {
    stubFetch(404);
    render(await Page({ params: Promise.resolve({ token: "abc" }) }));
    expect(screen.getByRole("alert")).toHaveTextContent("Link nieprawidłowy lub wygasł");
    expect(screen.queryByText(/dashboard/i)).toBeNull();
  });

  it.each([
    ["podpis", SignPage],
    ["karta Championa", PublicChampionCardPage],
  ])("%s: awaria serwera nie udaje wygasłego linku", async (_name, Page) => {
    stubFetch(503);
    render(await Page({ params: Promise.resolve({ token: "abc" }) }));
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się otworzyć linku");
  });
});
