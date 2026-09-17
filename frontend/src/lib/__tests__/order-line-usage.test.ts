import { describe, expect, it } from "vitest";

import {
  consultantUsageSentence,
  hasScopedMd,
  lineHasSettlements,
  lineScopeRemaining,
  lineScopeUsage,
  usageAmount,
} from "@/lib/order-line-usage";

const base = {
  consultant_name: "Marian Odeszły",
  is_active: false,
  invoiced_total: null,
  md_used: null,
  rate_revenue: null,
  removed_from_order: false,
  cooperation_ended_on: "2031-08-12",
};

describe("wykorzystanie osoby na zamówieniu — to samo zdanie dla MD i kosztowych", () => {
  it("zamówienie kosztowe: kwota zafakturowana przed zakończeniem współpracy", () => {
    const sentence = consultantUsageSentence(
      { is_cost_based: true },
      { ...base, invoiced_total: 12500 },
    );
    expect(sentence).toMatch(
      /^Marian Odeszły wykorzystał\(a\) 12\s500,00\szł na tym zamówieniu przed zakończeniem współpracy — ta kwota nie wraca do puli/,
    );
  });

  it("zamówienie MD: MD i ich wartość, gdy stawka jest widoczna", () => {
    expect(
      usageAmount({ is_cost_based: false }, { ...base, md_used: 12.5, rate_revenue: 1000 }),
    ).toMatch(/^12\s500,00\szł \/ 12,5 MD$/);
  });

  it("rola bez finansów widzi same MD, bez kwoty", () => {
    expect(usageAmount({ is_cost_based: false }, { ...base, md_used: 7 })).toBe("7 MD");
  });

  it("osoba usunięta z zamówienia bez zakończonej współpracy", () => {
    expect(
      consultantUsageSentence(
        { is_cost_based: false },
        { ...base, md_used: 3, cooperation_ended_on: null, removed_from_order: true },
      ),
    ).toContain("przed usunięciem z zamówienia");
  });

  it("aktywna osoba albo zero zużycia — bez zdania", () => {
    expect(
      consultantUsageSentence({ is_cost_based: false }, { ...base, is_active: true, md_used: 3 }),
    ).toBeNull();
    expect(consultantUsageSentence({ is_cost_based: true }, { ...base, invoiced_total: 0 })).toBeNull();
  });
});

describe("lineScopeUsage — podstawa + opcja (CeZ)", () => {
  const scoped = {
    md_total: 190,
    md_optional_total: 170,
    md_base_used: 154,
    md_optional_used: 0,
    md_used: 154,
  };

  const cez = {
    executive_contract: {
      id: 71,
      number: "CeZ/242/2025",
      status: "active" as const,
      framework_contract_id: 12,
      project_part: "cz2",
    },
  };
  const plainGroup = { executive_contract: null };

  it("serwerowy podział wygrywa; suma i procent z całości (podstawa + opcja)", () => {
    expect(hasScopedMd(scoped, cez)).toBe(true);
    expect(lineScopeUsage(scoped)).toEqual({
      baseUsed: 154,
      baseTotal: 190,
      optionalUsed: 0,
      optionalTotal: 170,
      totalUsed: 154,
      totalBudget: 360,
      pct: (154 / 360) * 100,
    });
  });

  it("brak opcji to `null`, nie zero — i nie wchodzi do budżetu", () => {
    const usage = lineScopeUsage({ ...scoped, md_optional_total: null, md_optional_used: null });
    expect(usage.optionalTotal).toBeNull();
    expect(usage.optionalUsed).toBeNull();
    expect(usage.totalBudget).toBe(190);
  });

  it("bez serwerowego podziału zużycie schodzi najpierw z podstawy, potem z opcji", () => {
    const usage = lineScopeUsage({
      md_total: 100,
      md_optional_total: 40,
      md_base_used: null,
      md_optional_used: null,
      md_used: 112,
    });
    expect(usage.baseUsed).toBe(100);
    expect(usage.optionalUsed).toBe(12);
    expect(usage.totalUsed).toBe(112);
  });

  it("linia BIK/Polkomtel bez zakresów nie jest „scoped” — zostaje stary pasek", () => {
    const plain = { md_total: 50, md_optional_total: null, md_base_used: null, md_optional_used: null, md_used: 10 };
    expect(hasScopedMd(plain, plainGroup)).toBe(false);
    expect(lineScopeUsage({ ...plain, md_total: 0 }).pct).toBeNull();
  });

  it("bramką jest umowa wykonawcza, nie `md_base_used` — backend zwraca podział każdej linii MD", () => {
    // Przegląd adwersarialny 09.2026: `md_base_used` przychodzi dla KAŻDEJ
    // linii z `md_total` (BIK/Polkomtel też), więc sam podział nie może
    // przełączać paska. Bez umowy wykonawczej na karcie — stary pasek.
    const bik = { md_total: 50, md_optional_total: null, md_base_used: 10, md_optional_used: null, md_used: 10 };
    expect(hasScopedMd(bik, plainGroup)).toBe(false);
    expect(hasScopedMd(bik, cez)).toBe(true);
    // Umowa wykonawcza, ale linia bez własnego budżetu MD — nie ma czego dzielić.
    expect(hasScopedMd({ ...bik, md_total: null, md_base_used: null }, cez)).toBe(false);
    // Zakres opcjonalny z odpowiedzi wystarcza sam — nie ma go bez umowy CeZ.
    expect(hasScopedMd({ ...bik, md_optional_total: 20 }, plainGroup)).toBe(true);
  });
});

describe("lineScopeRemaining — karta konsultanta CeZ", () => {
  const scoped = {
    md_total: 190,
    md_optional_total: 170,
    md_base_used: 184,
    md_optional_used: 0,
    md_used: 184,
    md_remaining: 176,
    md_manual_adjustment: 0,
  };

  it("pozostało osobno w podstawie, opcji i łącznie (serwerowe md_remaining)", () => {
    const rest = lineScopeRemaining(scoped);
    expect(rest.baseRemaining).toBe(6);
    expect(rest.optionalRemaining).toBe(170);
    expect(rest.totalRemaining).toBe(176);
    expect(Math.round(rest.basePct!)).toBe(97);
    expect(rest.optionalPct).toBe(0);
    expect(rest.adjustment).toBe(0);
  });

  it("brak opcji w umowie nie dolicza jej limitu do łącznie", () => {
    const rest = lineScopeRemaining({
      md_total: 340,
      md_optional_total: null,
      md_base_used: 155,
      md_optional_used: null,
      md_used: 155,
      md_remaining: null,
    });
    expect(rest.optionalRemaining).toBeNull();
    expect(rest.optionalPct).toBeNull();
    expect(rest.totalRemaining).toBe(185);
  });

  it("korekta ręczna wchodzi do łącznie i jest zwracana osobno; przekroczenie jest ujemne", () => {
    const adjusted = lineScopeRemaining({ ...scoped, md_remaining: null, md_manual_adjustment: 10 });
    expect(adjusted.totalRemaining).toBe(186);
    expect(adjusted.adjustment).toBe(10);

    const exceeded = lineScopeRemaining({
      md_total: 100,
      md_optional_total: null,
      md_base_used: 108,
      md_optional_used: null,
      md_used: 108,
      md_remaining: -8,
    });
    expect(exceeded.baseRemaining).toBe(-8);
    expect(exceeded.totalRemaining).toBe(-8);
  });
});

describe("lineHasSettlements — usunięcie z zamówienia kasuje linię, więc rozliczenia je blokują", () => {
  it("brak MD i faktur → można usunąć", () => {
    expect(lineHasSettlements({ md_used: null, invoiced_total: null })).toBe(false);
    expect(lineHasSettlements({ md_used: 0, invoiced_total: 0 })).toBe(false);
  });

  it("zaraportowane MD albo faktury → blokuje", () => {
    expect(lineHasSettlements({ md_used: 3, invoiced_total: null })).toBe(true);
    expect(lineHasSettlements({ md_used: null, invoiced_total: 1200 })).toBe(true);
  });
});
