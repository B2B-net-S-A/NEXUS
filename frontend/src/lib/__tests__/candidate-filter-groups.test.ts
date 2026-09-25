import { describe, expect, it } from "vitest";
import { DEFAULT_FILTERS, type CandidateFilters } from "@/lib/url-filters";
import {
  filterGroupCounts,
  isChipShownOnFilterBar,
  locationSummary,
  rateSummary,
  remoteSummary,
} from "@/lib/candidate-filter-groups";

const NO_STAGE = {
  stages: [],
  currentOnly: false,
  clientIds: [],
  movedByIds: [],
  movedAfter: "",
  movedBefore: "",
};
const NO_SKILLS = { required: [], preferred: [], excluded: [] };

function withFilters(patch: Partial<CandidateFilters>): CandidateFilters {
  return { ...DEFAULT_FILTERS, ...patch };
}

describe("rateSummary", () => {
  it("opisuje oba końce, sam dół i samą górę", () => {
    expect(rateSummary({ rateMin: 120, rateMax: 160 })).toBe("120–160 zł/h");
    expect(rateSummary({ rateMin: 120, rateMax: null })).toBe("od 120 zł/h");
    expect(rateSummary({ rateMin: null, rateMax: 160 })).toBe("do 160 zł/h");
    expect(rateSummary({ rateMin: null, rateMax: null })).toBeNull();
  });

  it("zero jest wartością, nie brakiem", () => {
    expect(rateSummary({ rateMin: 0, rateMax: null })).toBe("od 0 zł/h");
  });
});

describe("locationSummary", () => {
  it("miasto, miasto z promieniem i miasto z województwem", () => {
    expect(locationSummary({ location: "Warszawa", locationRadiusKm: null, voivodeships: [] })).toBe(
      "Warszawa",
    );
    expect(locationSummary({ location: "Warszawa", locationRadiusKm: 25, voivodeships: [] })).toBe(
      "Warszawa +25 km",
    );
    expect(
      locationSummary({ location: "Kraków", locationRadiusKm: null, voivodeships: ["mazowieckie"] }),
    ).toBe("Kraków, mazowieckie");
  });

  it("same województwa: jedno z nazwy, kilka z liczbą w dobrej formie", () => {
    const one = { location: "", locationRadiusKm: null };
    expect(locationSummary({ ...one, voivodeships: ["śląskie"] })).toBe("śląskie");
    expect(locationSummary({ ...one, voivodeships: ["a", "b"] })).toBe("2 województwa");
    expect(locationSummary({ ...one, voivodeships: ["a", "b", "c", "d", "e"] })).toBe(
      "5 województw",
    );
  });

  it("promień bez miasta i same spacje to brak wartości", () => {
    expect(locationSummary({ location: "  ", locationRadiusKm: 25, voivodeships: [] })).toBeNull();
  });
});

describe("remoteSummary", () => {
  it("łączy tryby w kolejności wyboru", () => {
    expect(remoteSummary({ remote: ["remote", "hybrid"] })).toBe("Zdalnie, Hybryda");
    expect(remoteSummary({ remote: [] })).toBeNull();
  });
});

describe("filterGroupCounts", () => {
  it("pusty stan to same zera", () => {
    expect(filterGroupCounts(DEFAULT_FILTERS, NO_STAGE, NO_SKILLS)).toEqual({
      rate: 0,
      location: 0,
      remote: 0,
      history: 0,
      skills: 0,
      availability: 0,
      more: 0,
    });
  });

  it("każdy filtr trafia do swojego przycisku", () => {
    const counts = filterGroupCounts(
      withFilters({
        rateMax: 160,
        location: "Warszawa",
        voivodeships: ["mazowieckie"],
        remote: ["remote"],
        recruitmentIds: [1, 2],
        contacted: "yes",
        contactedByIds: [4],
        availability: ["open_to_offers"],
        languages: ["en:B2"],
        status: ["active"],
        qAny: [["spring"], ["react", "vue"]],
      }),
      { ...NO_STAGE, stages: ["cv_sent"], movedAfter: "2026-01-01" },
      { required: ["Java"], preferred: [], excluded: ["PHP"] },
    );
    expect(counts).toEqual({
      rate: 1,
      location: 2,
      remote: 1,
      // 2 rekrutacje + etap + data etapu + kontakt + osoba kontaktu
      history: 6,
      skills: 2,
      availability: 1,
      // język + status; wszystkie wiersze słów kluczowych stoją na pasku
      // nad tabelą (25.09.2026), więc „Więcej filtrów” ich nie liczy
      more: 2,
    });
  });
});

describe("isChipShownOnFilterBar", () => {
  it("ukrywa chipy z wartością na pasku, zostawia resztę", () => {
    for (const key of ["rate", "loc", "q_scope", "woj:śląskie", "remote:hybrid", "q_all:java", "q_any:0:spring", "q_any:3:react", "q_none:junior"]) {
      expect(isChipShownOnFilterBar(key)).toBe(true);
    }
    for (const key of ["q", "status:active", "lang:en:B2", "client_hist:3"]) {
      expect(isChipShownOnFilterBar(key)).toBe(false);
    }
  });
});
