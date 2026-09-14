import { describe, expect, it } from "vitest";

import type { CandidateSearchRequest } from "@/lib/candidate-search-api";
import {
  EXPERIENCE_RANGE_REVERSED_MSG,
  RATE_RANGE_REVERSED_MSG,
  SEARCH_REQUEST_URL_PARAM,
  decodeSearchRequest,
  encodeSearchRequest,
  experienceRangeError,
  searchRequestFingerprint,
  searchRequestValidationError,
} from "@/lib/candidate-search-request";

const BASE: CandidateSearchRequest = {
  q: null,
  q_all: [],
  q_any: [],
  q_any_groups: [],
  q_none: [],
  competence_category_ids: [],
  skills_must: [],
  skills_any: [],
  skills_none: [],
  languages: [],
  location_cities: [],
  status: [],
  availability_status: [],
  tags: [],
  sort: "relevance",
  page: 1,
  page_size: 50,
  search_mode: "hybrid",
  exclude_in_job_id: 42,
};

describe("candidate-search-request — stan w URL (UAT B29)", () => {
  it("baza daje pusty URL", () => {
    expect(encodeSearchRequest(BASE, BASE).toString()).toBe("");
    expect(searchRequestFingerprint({ ...BASE }, BASE)).toBe("");
  });

  it("round-trip: filtry, sortowanie i strona wracają z URL-a", () => {
    const request: CandidateSearchRequest = {
      ...BASE,
      q: "tester bankowość",
      q_none: ["Selenium"],
      q_any_groups: [["java", "kotlin"]],
      skills_must: ["Python"],
      experience_years_min: 2,
      experience_years_max: 6,
      languages: [{ code: "EN", min_level: "B2" }],
      has_cv: true,
      sort: "recent",
      page: 2,
    };
    const params = encodeSearchRequest(request, BASE);
    const raw = params.get(SEARCH_REQUEST_URL_PARAM);
    expect(raw).toBeTruthy();
    expect(decodeSearchRequest(raw, BASE)).toEqual(request);
  });

  it("kontekst rekrutacji nie trafia do URL-a i nie da się go wstrzyknąć", () => {
    const params = encodeSearchRequest({ ...BASE, exclude_in_job_id: 7 }, BASE);
    expect(params.toString()).toBe("");
    const decoded = decodeSearchRequest(
      JSON.stringify({ exclude_in_job_id: 999, q: "x" }),
      BASE,
    );
    expect(decoded.exclude_in_job_id).toBe(42);
    expect(decoded.q).toBe("x");
  });

  it("nieczytelny lub obcy parametr = baza, nigdy wyjątek", () => {
    expect(decodeSearchRequest("{nie-json", BASE)).toEqual(BASE);
    expect(decodeSearchRequest("[1,2]", BASE)).toEqual(BASE);
    expect(decodeSearchRequest(null, BASE)).toEqual(BASE);
    expect(decodeSearchRequest(JSON.stringify({ __proto__: 1, foo: "bar" }), BASE)).toEqual(
      BASE,
    );
  });

  it("strona i rozmiar strony przycięte do zakresu backendu", () => {
    expect(decodeSearchRequest(JSON.stringify({ page: 0 }), BASE).page).toBe(1);
    expect(decodeSearchRequest(JSON.stringify({ page: "abc" }), BASE).page).toBe(1);
    expect(decodeSearchRequest(JSON.stringify({ page: 129 }), BASE).page).toBe(129);
    expect(decodeSearchRequest(JSON.stringify({ page_size: 5000 }), BASE).page_size).toBe(50);
  });

  it("null i undefined znaczą to samo — nie robią szumu w URL-u", () => {
    expect(
      encodeSearchRequest({ ...BASE, experience_years_min: null }, BASE).toString(),
    ).toBe("");
  });
});

describe("candidate-search-request — walidacja przedziałów (UAT B28)", () => {
  it("min > max lat doświadczenia to błąd po polsku", () => {
    expect(
      experienceRangeError({ experience_years_min: 10, experience_years_max: 2 }),
    ).toBe(EXPERIENCE_RANGE_REVERSED_MSG);
    expect(
      searchRequestValidationError({
        ...BASE,
        experience_years_min: 10,
        experience_years_max: 2,
      }),
    ).toBe(EXPERIENCE_RANGE_REVERSED_MSG);
  });

  it("przedział poprawny, równy albo otwarty przechodzi", () => {
    expect(experienceRangeError({ experience_years_min: 2, experience_years_max: 6 })).toBeNull();
    expect(experienceRangeError({ experience_years_min: 3, experience_years_max: 3 })).toBeNull();
    expect(experienceRangeError({ experience_years_min: 10, experience_years_max: null })).toBeNull();
    expect(searchRequestValidationError(BASE)).toBeNull();
  });

  it("odwrócone widełki stawki mają własny komunikat", () => {
    expect(
      searchRequestValidationError({ ...BASE, rate_hourly_min: 200, rate_hourly_max: 100 }),
    ).toBe(RATE_RANGE_REVERSED_MSG);
  });
});
