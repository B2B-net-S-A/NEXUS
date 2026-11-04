import { describe, expect, it } from "vitest";

import { RATE_OVER_BUDGET_WARN_MAX_PCT, rateBudgetBadge } from "@/lib/rate-budget-badge";

const badge = (rateHourly: unknown, budgetHourly: unknown, currency?: string | null) =>
  rateBudgetBadge({
    rateHourly: rateHourly as number | string | null,
    budgetHourly: budgetHourly as number | string | null,
    ...(currency !== undefined ? { currency } : {}),
  });

describe("rateBudgetBadge — stawka względem budżetu (D3, 19.10.2026)", () => {
  it("w budżecie: poniżej i RÓWNO górna granica", () => {
    expect(badge(120, 140)).toMatchObject({ tone: "in", label: "w budżecie · 120 zł/h" });
    expect(badge(140, 140)).toMatchObject({ tone: "in", label: "w budżecie · 140 zł/h" });
    // Kwoty z API przychodzą jako tekst (`Decimal`).
    expect(badge("140.00", "140.00")).toMatchObject({ tone: "in", label: "w budżecie · 140 zł/h" });
  });

  it("ponad budżet do +15% włącznie to ostrzeżenie", () => {
    expect(badge(160, 140)).toMatchObject({ tone: "over", label: "+14% ponad budżet · 160 zł/h" });
    // Dokładnie +15% (161 / 140) — jeszcze ostrzeżenie.
    expect(badge(161, 140)).toMatchObject({ tone: "over", label: "+15% ponad budżet · 161 zł/h" });
    expect(badge(115, 100)).toMatchObject({ tone: "over", label: "+15% ponad budżet · 115 zł/h" });
    expect(RATE_OVER_BUDGET_WARN_MAX_PCT).toBe(15);
  });

  it("powyżej +15% ton „destructive-muted”; tuż nad progiem z miejscem po przecinku", () => {
    // +15,1% — zaokrąglone „+15%” w innym kolorze myliłoby, więc „+15,1%”.
    expect(badge(115.1, 100)).toMatchObject({ tone: "far", label: "+15,1% ponad budżet · 115 zł/h" });
    expect(badge(125, 100)).toMatchObject({ tone: "far", label: "+25% ponad budżet · 125 zł/h" });
  });

  it("minimalne przekroczenie to co najmniej +1%, nigdy „+0%”", () => {
    expect(badge(140.4, 140)).toMatchObject({ tone: "over", label: "+1% ponad budżet · 140 zł/h" });
  });

  it("rekrutacja bez budżetu: sama kwota, bez oceny", () => {
    for (const budget of [null, undefined, 0, -5, "", "abc"]) {
      expect(badge(140, budget)).toMatchObject({ tone: "plain", label: "140 zł/h" });
    }
  });

  it("obca waluta: sama kwota z kodem, bez porównania", () => {
    expect(badge(30, 140, "EUR")).toMatchObject({ tone: "plain", label: "30 EUR/h" });
    // „zł”/„ZŁ” z importu i brak waluty to złotówki.
    expect(badge(120, 140, "zł")).toMatchObject({ tone: "in" });
    expect(badge(120, 140, null)).toMatchObject({ tone: "in" });
  });

  it("brak stawki: nic", () => {
    for (const rate of [null, undefined, 0, -10, "", "abc", Number.NaN]) {
      expect(badge(rate, 140)).toBeNull();
    }
  });

  it("podpowiedź mówi stawkę, budżet i że stawka nie zmienia dopasowania", () => {
    expect(badge(160, 140)?.title).toBe(
      "Stawka kandydata 160 zł/h, budżet rekrutacji do 140,00 PLN/h. Informacja — stawka nie zmienia dopasowania.",
    );
    expect(badge(140, null)?.title).toBe("Stawka kandydata 140 zł/h — rekrutacja nie ma budżetu.");
  });
});
