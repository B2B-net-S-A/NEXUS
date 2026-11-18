import { describe, expect, it } from "vitest";
import {
  NO_REJECTION_FILTER,
  cycleFacetKey,
  rejectionFilterCount,
  rejectionFilterSummary,
  rejectionKeyLabel,
} from "@/lib/candidate-last-rejection";
import { decodeFilters, encodeFilters, DEFAULT_FILTERS, filtersToApiParams } from "@/lib/url-filters";

describe("filtr „Powód odrzucenia”", () => {
  const f = (patch: Partial<typeof NO_REJECTION_FILTER>) => ({ ...NO_REJECTION_FILTER, ...patch });

  it("licznik i podsumowania", () => {
    expect(rejectionFilterCount(NO_REJECTION_FILTER)).toBe(0);
    expect(rejectionFilterSummary(NO_REJECTION_FILTER)).toBeNull();
    // Samo „Ukryj” niczego nie zawęża.
    expect(rejectionFilterCount(f({ rejectionExclude: true }))).toBe(0);
    const set = f({
      rejectionKeys: ["r:Brak doświadczenia", "t:Po CV"],
      rejectionBy: ["client"],
      rejectionWithinMonths: 3,
    });
    expect(rejectionFilterCount(set)).toBe(4);
    expect(rejectionFilterSummary(set)).toBe(
      "Odrzucenie: Brak doświadczenia, Traffit · Po CV, Klient · 3 mies.",
    );
    expect(rejectionFilterSummary({ ...set, rejectionExclude: true })).toBe(
      "Ukryte odrzucenie: Brak doświadczenia, Traffit · Po CV, Klient · 3 mies.",
    );
    expect(rejectionKeyLabel("none")).toBe("Bez powodu");
  });

  it("klik w pasek: pokaż tylko → ukryj → zdejmij", () => {
    const first = cycleFacetKey(NO_REJECTION_FILTER, "t:Po CV");
    expect(first).toEqual({ rejectionKeys: ["t:Po CV"], rejectionExclude: false });
    const second = cycleFacetKey(f({ rejectionKeys: ["t:Po CV"] }), "t:Po CV");
    expect(second).toEqual({ rejectionExclude: true });
    const third = cycleFacetKey(f({ rejectionKeys: ["t:Po CV"], rejectionExclude: true }), "t:Po CV");
    expect(third).toEqual({ rejectionKeys: [], rejectionExclude: false });
    // Przy kilku powodach klik zdejmuje jeden, tryb zostaje.
    const many = cycleFacetKey(f({ rejectionKeys: ["t:Po CV", "r:Inne"] }), "r:Inne");
    expect(many).toEqual({ rejectionKeys: ["t:Po CV"], rejectionExclude: false });
  });

  it("adres i API: etykieta z przecinkami przechodzi w obie strony, samo „Ukryj” znika", () => {
    const filters = {
      ...DEFAULT_FILTERS,
      rejectionKeys: ["r:Forma umowy (UoP, B2B, etat)", "none"],
      rejectionBy: ["us" as const],
      rejectionWithinMonths: 12 as const,
      rejectionExclude: true,
    };
    const back = decodeFilters(encodeFilters(filters));
    expect(back.rejectionKeys).toEqual(filters.rejectionKeys);
    expect(back.rejectionBy).toEqual(["us"]);
    expect(back.rejectionWithinMonths).toBe(12);
    expect(back.rejectionExclude).toBe(true);
    const api = filtersToApiParams(filters, 1);
    expect(api.rejection_key).toEqual(filters.rejectionKeys);
    expect(api.rejection_by).toEqual(["us"]);
    expect(api.rejection_within_months).toBe(12);
    expect(api.rejection_exclude).toBe(true);

    const onlyHide = { ...DEFAULT_FILTERS, rejectionExclude: true };
    expect(encodeFilters(onlyHide).has("rej_x")).toBe(false);
    expect(filtersToApiParams(onlyHide, 1).rejection_exclude).toBeUndefined();
    // Śmieci w adresie nie przechodzą.
    const junk = decodeFilters(new URLSearchParams("rej_by=dl,client&rej_m=6"));
    expect(junk.rejectionBy).toEqual(["client"]);
    expect(junk.rejectionWithinMonths).toBe(0);
  });
});

describe("zapytanie paska", () => {
  it("te same kryteria co lista, bez strony, sortowania i danych wierszy", async () => {
    const { candidatesListApiParams, rejectionFacetsApiParams } = await import(
      "@/components/v2/pages/CandidatesListV2"
    );
    const filters = { ...DEFAULT_FILTERS, q: "AI Engineer", rejectionKeys: ["t:Po CV"] };
    const list = candidatesListApiParams(filters, 1, 50);
    // 18.11.2026: lista prosi o „Ostatnio z osobą” zamiast kolumny odrzucenia.
    expect(list).toMatchObject({ include_recent_facts: true });
    expect(list).not.toHaveProperty("include_last_rejection");
    const page1 = rejectionFacetsApiParams(list);
    const page3 = rejectionFacetsApiParams(candidatesListApiParams({ ...filters, page: 3 }, 3, 50));
    expect(page3).toEqual(page1);
    expect(page1).toMatchObject({
      q: "AI Engineer",
      rejection_key: ["t:Po CV"],
      page: 1,
      page_size: 1,
      include_rejection_facets: true,
    });
    expect(page1).not.toHaveProperty("sort");
    // Pasek nie potrzebuje danych wierszy, w tym „Ostatnio z osobą”.
    expect(page1).not.toHaveProperty("include_recent_facts");
    expect(page1).not.toHaveProperty("include_active_recruitments");
  });
});
