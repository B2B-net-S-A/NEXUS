import { describe, expect, it } from "vitest";

import { DEFAULT_FILTERS, decodeFilters, effectiveSort, encodeFilters } from "@/lib/url-filters";

const base = { ...DEFAULT_FILTERS };

describe("kolejność „Dopasowanie” (sort=match, decyzja 25.09.2026)", () => {
  it("wiersze wymagań bez tekstu i bez jawnego wyboru → match", () => {
    expect(effectiveSort({ ...base, qAny: [["java"], ["spring"]] })).toBe("match");
  });

  it("„Szukaj ręcznie” (jedna rekrutacja, osoby spoza niej) → match także bez wymagań", () => {
    expect(
      effectiveSort({ ...base, recruitmentIds: [7], recruitmentMatch: "not_assigned" }),
    ).toBe("match");
  });

  it("filtr „brał udział w rekrutacji” nie jest kontekstem dopasowania", () => {
    expect(effectiveSort({ ...base, recruitmentIds: [7], recruitmentMatch: "assigned" })).toBe(
      "newest",
    );
  });

  it("wpisany tekst wygrywa (trafność), jawne „Najnowsi” wygrywa zawsze", () => {
    expect(effectiveSort({ ...base, q: "java developer", qAny: [["java"]] })).toBe("relevance");
    expect(effectiveSort({ ...base, qAny: [["java"]], sortExplicit: true })).toBe("newest");
  });

  it("jawne „match” bez kontekstu wraca do najnowszych", () => {
    expect(effectiveSort({ ...base, sort: "match" })).toBe("newest");
  });

  it("jawne „match” przeżywa adres", () => {
    const filters = decodeFilters(encodeFilters({ ...base, qAny: [["java"]], sort: "match" }));
    expect(filters.sort).toBe("match");
  });
});
