import { describe, expect, it } from "vitest";

import { consultantUsageSentence, usageAmount } from "@/lib/order-line-usage";

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
