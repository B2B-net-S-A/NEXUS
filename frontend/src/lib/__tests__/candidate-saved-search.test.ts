import { describe, expect, it } from "vitest";

import {
  buildCandidateSavedSearchPayload,
  filtersFromCandidateSavedSearch,
  listQsFromSavedSearch,
} from "@/lib/candidate-saved-search";
import { decodeFilters } from "@/lib/url-filters";

describe("candidate saved searches", () => {
  it("writes v2 criteria without transient presentation or include fields", () => {
    const payload = buildCandidateSavedSearchPayload(
      "q=python&recr=17&recr_mode=not_assigned&page=8&view=tiles&ss=9",
    );

    expect(payload.version).toBe(2);
    expect(payload.qs).toBe("q=python&recr=17&recr_mode=not_assigned");
    expect(payload.api).toMatchObject({
      q: "python",
      recruitment_id: [17],
      recruitment_match: "not_assigned",
    });
    expect(payload.api).not.toHaveProperty("include_match_stats");
  });

  it("restores a legacy v1 record from defaults and preserves current view", () => {
    const restored = filtersFromCandidateSavedSearch(
      { qs: "q=java&status=active&recr=12" },
      "tiles",
    );

    expect(restored).toMatchObject({
      q: "java",
      status: ["active"],
      recruitmentIds: [12],
      page: 1,
      view: "tiles",
      savedSearchId: null,
    });
    expect(restored.openTo).toEqual([]);
  });

  it("restores v2 qs and ignores stale API presentation flags", () => {
    const restored = filtersFromCandidateSavedSearch(
      {
        version: 2,
        qs: "open_to=expert_consult&rcj=2&recr=5%2C7",
        api: { include_match_stats: true, page: 99 },
      },
      "list",
    );

    expect(restored.openTo).toEqual(["expert_consult"]);
    expect(restored.recentlyChangedJobs).toBe(2);
    expect(restored.recruitmentIds).toEqual([5, 7]);
    expect(restored.page).toBe(1);
    expect(restored.view).toBe("list");
  });

  it("otwiera na liście zapis z dawnej wyszukiwarki ręcznej jako wiersze wymagań", () => {
    // Kształt zapisu z produkcji (25.09.2026): surowe żądanie wyszukiwarki bez
    // `qs`. Od jednej listy i „Szukaj ręcznie” w oknie rekrutacji nie ma już
    // ekranu, który by go otworzył — lista pokazywała natywny alert.
    const qs = listQsFromSavedSearch({
      q_all: ["tester"],
      q_none: ["junior"],
      skills_any: ["Selenium", "Postman"],
      skills_must: ["Testing"],
      skills_none: ["PHP"],
      q_any_groups: [["bank", "bankowość", "finanse", "sektor finansowy"]],
      location_cities: ["Warszawa"],
      experience_years_max: 6,
      experience_years_min: 2,
    });
    const decoded = decodeFilters(new URLSearchParams(qs));

    expect(decoded.qAny).toEqual([
      ["tester"],
      ["bank", "bankowość", "finanse", "sektor finansowy"],
    ]);
    expect(decoded.qNone).toEqual(["junior"]);
    // „Musi mieć” i „którekolwiek” wyszukiwarki były tylko rankingiem.
    expect(decoded.skillsPreferred).toEqual(["Testing", "Selenium", "Postman"]);
    expect(decoded.skillsExpr).toContain("PHP");
    expect(decoded.location).toBe("Warszawa");
    expect(decoded.experienceMin).toBe(2);
    expect(decoded.experienceMax).toBe(6);
  });

  it("zapis v3 z wyszukiwarki (origin search_request) też otwiera się na liście", () => {
    const qs = listQsFromSavedSearch({
      version: 3,
      semantics_version: 2,
      origin: "search_request",
      request: {
        q_all: ["python"],
        q_any_groups: [["django", "flask"]],
        skills_required: ["AWS"],
      },
      legacy: { q_all: ["python"] },
    });
    const decoded = decodeFilters(new URLSearchParams(qs));

    expect(decoded.qAny).toEqual([["python"], ["django", "flask"]]);
    expect(decoded.skillsExpr).toContain("AWS");
  });

  it("zapis listy otwiera się bez zmian", () => {
    expect(listQsFromSavedSearch({ version: 2, qs: "q_any=java", api: {} })).toBe("q_any=java");
    expect(listQsFromSavedSearch(null)).toBe("");
  });
});
