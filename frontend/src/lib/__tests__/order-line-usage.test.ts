import { describe, expect, it } from "vitest";

import {
  consultantUsageSentence,
  hasScopedMd,
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

  it("serwerowy podział wygrywa; suma i procent z całości (podstawa + opcja)", () => {
    expect(hasScopedMd(scoped)).toBe(true);
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
    expect(hasScopedMd(plain)).toBe(false);
    expect(lineScopeUsage({ ...plain, md_total: 0 }).pct).toBeNull();
  });
});
