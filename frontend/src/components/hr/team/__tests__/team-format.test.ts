import { describe, expect, it } from "vitest";

import { bonusCell, leaveCell } from "../team-format";

describe("„Mój zespół” — komórki", () => {
  it("nieobecności: pula tylko u osób z pulą, reszta — zaplanowane dni", () => {
    expect(
      leaveCell({ has_pool: true, has_paid_pool: true, remaining_days: "11.5", planned_days: "3.0", pending_days: "0.0" }),
    ).toEqual({ text: "zostało 11,5 dnia urlopu", sub: "zaplanowane 3 dni" });
    expect(
      leaveCell({ has_pool: false, has_paid_pool: false, remaining_days: null, planned_days: "2.0", pending_days: "1.0" }),
    ).toEqual({ text: "zaplanowane 2 dni", sub: "czeka 1 dzień" });
    expect(
      leaveCell({ has_pool: false, has_paid_pool: false, remaining_days: null, planned_days: "0.0", pending_days: "0.0" }).text,
    ).toBe("nic zaplanowanego");
    expect(leaveCell(null).text).toBe("—");
    // B2B z umowną pulą: „z puli”, nie „urlopu” (D4).
    expect(
      leaveCell(
        { has_pool: true, has_paid_pool: true, remaining_days: "5.0", planned_days: "0.0", pending_days: "0.0" },
        "b2b",
      ).text,
    ).toBe("zostało 5 dni z puli");
  });

  it("wiersz puli z zerem (B2B bez płatnych dni) to nie „zostało 0 dni” — liczy się płatna pula", () => {
    const zero = leaveCell(
      { has_pool: true, has_paid_pool: false, remaining_days: "0.0", planned_days: "2.0", pending_days: "0.0" },
      "b2b",
    );
    expect(zero.text).not.toMatch(/zostało/);
    expect(zero).toEqual({ text: "zaplanowane 2 dni", sub: undefined });
  });

  it("premie: liczba i suma, propozycje do wiadomości; brak prawa to „—”, nie zero", () => {
    const cell = bonusCell({
      count: 2,
      proposals: 1,
      totals: [{ currency: "PLN", amount: "3000.00" }],
      items: [],
    });
    // Kwota jak w całej aplikacji (`@/lib/money`): dwa miejsca po przecinku.
    expect(cell.text).toBe("2 · 3000,00\u00a0zł");
    expect(cell.sub).toBe("1 propozycja — decydują Płace");
    expect(bonusCell(null).text).toBe("—");
    expect(bonusCell({ count: 0, proposals: 0, totals: [], items: [] }).text).toBe("—");
  });

  it("propozycje odmieniane po polsku (było „5 propozycje”)", () => {
    const sub = (proposals: number) =>
      bonusCell({ count: 6, proposals, totals: [{ currency: "PLN", amount: "100.00" }], items: [] }).sub;
    expect(sub(2)).toBe("2 propozycje — decydują Płace");
    expect(sub(5)).toBe("5 propozycji — decydują Płace");
    expect(sub(12)).toBe("12 propozycji — decydują Płace");
    expect(sub(22)).toBe("22 propozycje — decydują Płace");
  });
});
