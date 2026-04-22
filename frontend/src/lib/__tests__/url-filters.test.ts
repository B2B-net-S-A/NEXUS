import { describe, it, expect } from "vitest";
import {
  CandidateFilters,
  DEFAULT_FILTERS,
  decodeFilters,
  encodeFilters,
  filtersEqual,
} from "@/lib/url-filters";

const sp = (qs: string) => new URLSearchParams(qs);

describe("url-filters", () => {
  it("encode(defaults) is empty — no noise in URL", () => {
    expect(encodeFilters(DEFAULT_FILTERS).toString()).toBe("");
  });

  it("decode(empty) returns defaults", () => {
    expect(decodeFilters(sp(""))).toEqual(DEFAULT_FILTERS);
  });

  it("round-trips every field", () => {
    const full: CandidateFilters = {
      q: "python dev",
      status: "active",
      sort: "name",
      page: 3,
      remote: ["remote", "hybrid"],
      skills: ["python", "aws"],
      skillCombine: "or",
      location: "Warszawa",
      poolIds: [3, 5],
      addedByIds: [12, 0],
      currentCompany: ["Google", "Intel, Inc."],
      pastCompany: ["Allegro"],
      currentTitle: ["Senior Engineer"],
      workedAtClientIds: [10, 11],
      view: "tiles",
      savedSearchId: 7,
    };
    const encoded = encodeFilters(full);
    expect(decodeFilters(encoded)).toEqual(full);
  });

  it("pipe-separator survives commas in company names", () => {
    const filters: CandidateFilters = {
      ...DEFAULT_FILTERS,
      currentCompany: ["Intel, Inc.", "Microsoft"],
    };
    const roundtrip = decodeFilters(encodeFilters(filters));
    expect(roundtrip.currentCompany).toEqual(["Intel, Inc.", "Microsoft"]);
  });

  it("ignores unknown params (forward-compat for saved searches)", () => {
    const decoded = decodeFilters(sp("q=foo&unknown=bar&future_filter=x"));
    expect(decoded.q).toBe("foo");
    expect(decoded.status).toBe("");
  });

  it("coerces bad sort/view/skillCombine/remote values to safe defaults", () => {
    const decoded = decodeFilters(
      sp("sort=xxx&view=pyramid&skill_combine=xor&remote=moon,remote,hybrid&page=-2")
    );
    expect(decoded.sort).toBe("newest");
    expect(decoded.view).toBe("list");
    expect(decoded.skillCombine).toBe("and");
    expect(decoded.remote).toEqual(["remote", "hybrid"]);
    expect(decoded.page).toBe(1);
  });

  it("treats 0 sentinel in addedByIds as 'system import'", () => {
    const decoded = decodeFilters(sp("added_by=0,12"));
    expect(decoded.addedByIds).toEqual([0, 12]);
  });

  it("omits skill_combine when only one skill selected", () => {
    const filters: CandidateFilters = {
      ...DEFAULT_FILTERS,
      skills: ["python"],
      skillCombine: "or",
    };
    expect(encodeFilters(filters).has("skill_combine")).toBe(false);
  });

  it("filtersEqual compares independent of field order", () => {
    const a: CandidateFilters = { ...DEFAULT_FILTERS, q: "x", poolIds: [1, 2] };
    const b: CandidateFilters = { ...DEFAULT_FILTERS, poolIds: [1, 2], q: "x" };
    expect(filtersEqual(a, b)).toBe(true);
  });
});
