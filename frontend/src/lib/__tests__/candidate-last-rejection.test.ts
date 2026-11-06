import { describe, expect, it } from "vitest";
import {
  NO_REJECTION_FILTER,
  cycleFacetKey,
  hasLaterLiveProcess,
  lastRejectionCell,
  rejectionFilterCount,
  rejectionFilterSummary,
  rejectionKeyLabel,
  type LastRejection,
} from "@/lib/candidate-last-rejection";
import { decodeFilters, encodeFilters, DEFAULT_FILTERS, filtersToApiParams } from "@/lib/url-filters";

const base: LastRejection = {
  key: "r:Brak doświadczenia",
  label: "Brak doświadczenia",
  who: "us",
  ended_by: "recruiter",
  note: null,
  at: "2026-10-16T13:48:46Z",
  job_id: 10,
  job_title: "Senior AI Engineer",
  client_name: "PKO BP",
  moved_by_name: "Rekruter Testowy",
};

describe("komórka „Ostatnie odrzucenie”", () => {
  it("powód ze słownika: powód, kto, klient i data", () => {
    const v = lastRejectionCell(base);
    expect(v.primary).toBe("Brak doświadczenia");
    expect(v.primaryIsNote).toBe(false);
    expect(v.whoLabel).toBe("My");
    expect(v.secondary).toBe("PKO BP · 16.10.2026");
    expect(v.title).toContain("Rekrutacja: Senior AI Engineer");
  });

  it("„Inne” pokazuje opis, DL ma własną etykietę", () => {
    const v = lastRejectionCell({
      ...base,
      key: "r:Inne",
      label: "Inne",
      ended_by: "delivery_lead",
      note: "podpisał umowę z inną firmą",
    });
    expect(v.primary).toBe("Inne · „podpisał umowę z inną firmą”");
    expect(v.whoLabel).toBe("DL");
  });

  it("Traffit bez powodu: opis kursywą, kategoria w drugiej linii", () => {
    const v = lastRejectionCell({
      ...base,
      key: "t:Po CV",
      label: "Traffit · Po CV",
      ended_by: null,
      note: "stawka 115",
    });
    expect(v.primary).toBe("„stawka 115”");
    expect(v.primaryIsNote).toBe(true);
    expect(v.who).toBe("traffit");
    expect(v.whoLabel).toBe("Traffit · Po CV");
  });

  it("bez powodu i opisu mówi to wprost", () => {
    const v = lastRejectionCell({ ...base, key: "none", label: "Bez powodu", ended_by: null });
    expect(v.primary).toBe("bez powodu");
  });

  it("Traffit bez opisu: kategoria w pierwszej linii, nie dwa razy", () => {
    const v = lastRejectionCell({ ...base, key: "t:Po CV", label: "Traffit · Po CV", ended_by: null });
    expect(v.primary).toBe("Po CV");
    expect(v.whoLabel).toBe("Traffit");
  });
});

describe("„potem: w toku”", () => {
  it("liczy tylko proces w innej rekrutacji, trwający i nowszy niż odrzucenie", () => {
    const later = { job_id: 11, stage: "screening", moved_at: "2026-10-20T10:00:00Z" };
    expect(hasLaterLiveProcess(base, [later])).toBe(true);
    expect(hasLaterLiveProcess(base, [{ ...later, moved_at: "2026-10-01T10:00:00Z" }])).toBe(false);
    expect(hasLaterLiveProcess(base, [{ ...later, stage: "rejected" }])).toBe(false);
    expect(hasLaterLiveProcess(base, [{ ...later, job_id: 10 }])).toBe(false);
    expect(hasLaterLiveProcess(base, null)).toBe(false);
  });
});

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
    const page1 = rejectionFacetsApiParams(candidatesListApiParams(filters, 1, 50));
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
    expect(page1).not.toHaveProperty("include_last_rejection");
    expect(page1).not.toHaveProperty("include_active_recruitments");
  });
});
