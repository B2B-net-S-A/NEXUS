import { describe, expect, it } from "vitest";

import { salesFigures } from "@/components/sales/ClientSalesTab";

const opp = (id: number, status: "open" | "won" | "lost", value: string | null, extra: Partial<{ won_at: string | null; currency: string }> = {}) => ({
  id,
  title: `Szansa ${id}`,
  stage: status,
  status,
  value,
  currency: "PLN",
  won_at: null,
  updated_at: "2026-11-01T00:00:00Z",
  ...extra,
});

describe("liczby Sprzedaży u klienta (19.11.2026)", () => {
  it("liczy otwarte, wygrane w 12 miesięcy i przegrane z sumą kwot", () => {
    const figures = salesFigures(
      [
        opp(1, "lost", "6720"),
        opp(2, "lost", "60480"),
        opp(3, "won", "1000", { won_at: "2026-03-01T00:00:00Z" }),
        opp(4, "won", "5000", { won_at: "2024-01-01T00:00:00Z" }),
        opp(5, "open", "40000"),
      ],
      "2026-11-19",
    );
    expect(figures.open).toEqual({ count: 1, value: expect.stringMatching(/^40\s000/) });
    expect(figures.won.count).toBe(1);
    expect(figures.lost.count).toBe(2);
    expect(figures.lost.value).toMatch(/^67\s200/);
  });

  it("kwot w różnych walutach nie sumuje", () => {
    const figures = salesFigures([opp(1, "lost", "100"), opp(2, "lost", "200", { currency: "EUR" })], "2026-11-19");
    expect(figures.lost).toEqual({ count: 2, value: null });
  });
});
