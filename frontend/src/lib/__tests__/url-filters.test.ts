import { describe, it, expect } from "vitest";
import {
  CandidateFilters,
  DEFAULT_FILTERS,
  decodeFilters,
  encodeFilterCriteria,
  encodeFilters,
  filtersEqual,
  filtersToApiCriteria,
  filtersToApiParams,
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
      status: ["active", "passive"],
      employment: ["available"],
      availability: ["actively_looking", "open_to_offers"],
      pipelineStage: ["new", "screening", "verified"],
      competenceCategoryIds: [4, 9],
      sort: "name",
      page: 3,
      remote: ["remote", "hybrid"],
      skillsExpr: "python OR aws",
      location: "Warszawa",
      poolIds: [3, 5],
      addedByIds: [12, 0],
      currentCompany: ["Google", "Intel, Inc."],
      pastCompany: ["Allegro"],
      currentTitle: ["Senior Engineer"],
      workedAtClientIds: [10, 11],
      recruitmentIds: [42, 7],
      recruitmentMatch: "not_assigned",
      experienceMin: 2,
      experienceMax: 30,
      rateMin: 80,
      rateMax: 250,
      stageMovedByIds: [4, 0],
      stageMovedAfter: "2026-05-01",
      stageMovedBefore: "2026-05-29",
      stageClientIds: [21, 33],
      stageCurrentOnly: true,
      openTo: ["side_projects", "expert_consult"],
      recentlyChangedJobs: 2,
      view: "tiles",
      savedSearchId: 7,
      qAll: ["react native", "typescript"],
      qAny: [
        ["next.js", "remix"],
        ["go", "rust"],
      ],
      qNone: ["junior", "stażysta"],
    };
    const encoded = encodeFilters(full);
    expect(decodeFilters(encoded)).toEqual(full);
  });

  it("advanced search buckets use pipe so commas in phrases survive", () => {
    const withCommas: CandidateFilters = {
      ...DEFAULT_FILTERS,
      qAll: ["Intel, Inc.", "A/B testing"],
    };
    const encoded = encodeFilters(withCommas);
    expect(encoded.get("q_all")).toBe("Intel, Inc.|A/B testing");
    expect(decodeFilters(encoded).qAll).toEqual(["Intel, Inc.", "A/B testing"]);
  });

  it("empty advanced buckets stay out of the URL", () => {
    const encoded = encodeFilters({
      ...DEFAULT_FILTERS,
      qAll: [],
      qAny: [],
      qNone: [],
    });
    expect(encoded.has("q_all")).toBe(false);
    expect(encoded.has("q_any")).toBe(false);
    expect(encoded.has("q_none")).toBe(false);
  });

  it("decodes advanced buckets from pipe-separated query string", () => {
    const decoded = decodeFilters(
      sp("q_all=react%20native|typescript&q_any=next.js&q_none=junior|stażysta"),
    );
    expect(decoded.qAll).toEqual(["react native", "typescript"]);
    expect(decoded.qAny).toEqual([["next.js"]]);
    expect(decoded.qNone).toEqual(["junior", "stażysta"]);
  });

  it("encodes ANY OR-groups as repeated q_any params and round-trips", () => {
    const filters: CandidateFilters = {
      ...DEFAULT_FILTERS,
      qAny: [
        ["React", "TypeScript"],
        ["Java", "Node.js"],
      ],
    };
    const encoded = encodeFilters(filters);
    expect(encoded.getAll("q_any")).toEqual(["React|TypeScript", "Java|Node.js"]);
    expect(decodeFilters(encoded).qAny).toEqual([
      ["React", "TypeScript"],
      ["Java", "Node.js"],
    ]);
  });

  it("decodes a legacy single q_any param as one OR-group (back-compat)", () => {
    const decoded = decodeFilters(sp("q_any=React|TypeScript"));
    expect(decoded.qAny).toEqual([["React", "TypeScript"]]);
  });

  it("drops empty ANY groups from the encoded URL", () => {
    const encoded = encodeFilters({
      ...DEFAULT_FILTERS,
      qAny: [["React"], [], ["Java"]],
    });
    expect(encoded.getAll("q_any")).toEqual(["React", "Java"]);
  });

  it("status / employment / availability accept multiple CSV values", () => {
    const decoded = decodeFilters(
      sp("status=active,passive&employment=at_client,available&availability=actively_looking"),
    );
    expect(decoded.status).toEqual(["active", "passive"]);
    expect(decoded.employment).toEqual(["at_client", "available"]);
    expect(decoded.availability).toEqual(["actively_looking"]);
  });

  it("status filters out unknown values (forward-compat)", () => {
    const decoded = decodeFilters(sp("status=active,bogus,blacklisted"));
    expect(decoded.status).toEqual(["active", "blacklisted"]);
  });

  it("pipeline stage accepts CSV and rejects unknown enum values", () => {
    const decoded = decodeFilters(
      sp("stage=new,bogus,screening,verified,not_a_stage"),
    );
    expect(decoded.pipelineStage).toEqual(["new", "screening", "verified"]);
  });

  it("empty pipelineStage stays out of URL", () => {
    expect(encodeFilters({ ...DEFAULT_FILTERS, pipelineStage: [] }).has("stage")).toBe(
      false,
    );
  });

  it("legacy single status string decodes as 1-element array", () => {
    const decoded = decodeFilters(sp("status=active"));
    expect(decoded.status).toEqual(["active"]);
  });

  it("experience bounds: null stays out of URL, values round-trip", () => {
    expect(encodeFilters(DEFAULT_FILTERS).has("exp_min")).toBe(false);
    expect(encodeFilters(DEFAULT_FILTERS).has("exp_max")).toBe(false);
    const decoded = decodeFilters(sp("exp_min=2&exp_max=30"));
    expect(decoded.experienceMin).toBe(2);
    expect(decoded.experienceMax).toBe(30);
    // A lone bound is valid (open-ended band).
    expect(decodeFilters(sp("exp_min=5")).experienceMax).toBeNull();
    expect(decodeFilters(sp("exp_max=10")).experienceMin).toBeNull();
  });

  it("experience bounds clamp to [0,60] and reject garbage", () => {
    expect(decodeFilters(sp("exp_min=999")).experienceMin).toBe(60);
    expect(decodeFilters(sp("exp_min=-4")).experienceMin).toBeNull();
    expect(decodeFilters(sp("exp_max=abc")).experienceMax).toBeNull();
    expect(decodeFilters(sp("exp_min=0")).experienceMin).toBe(0);
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
    expect(decoded.status).toEqual([]);
  });

  it("coerces bad sort/view/remote values to safe defaults", () => {
    const decoded = decodeFilters(
      sp("sort=xxx&view=pyramid&remote=moon,remote,hybrid&page=-2")
    );
    expect(decoded.sort).toBe("newest");
    expect(decoded.view).toBe("list");
    expect(decoded.remote).toEqual(["remote", "hybrid"]);
    expect(decoded.page).toBe(1);
  });

  it("round-trips relevance, open-to and recently changed jobs", () => {
    const filters: CandidateFilters = {
      ...DEFAULT_FILTERS,
      sort: "relevance",
      openTo: ["side_projects", "sales_support"],
      recentlyChangedJobs: 3,
    };
    const encoded = encodeFilters(filters);
    expect(encoded.get("sort")).toBe("relevance");
    expect(encoded.get("open_to")).toBe("side_projects,sales_support");
    expect(encoded.get("rcj")).toBe("3");
    expect(decodeFilters(encoded)).toEqual(filters);
  });

  it("accepts repeated open_to values and rejects invalid rcj", () => {
    const decoded = decodeFilters(
      sp("open_to=side_projects&open_to=sales_support,expert_consult&rcj=7"),
    );
    expect(decoded.openTo).toEqual([
      "side_projects",
      "sales_support",
      "expert_consult",
    ]);
    expect(decoded.recentlyChangedJobs).toBeNull();
  });

  it("saved-search criteria omit transient page, view and saved-search id", () => {
    const encoded = encodeFilterCriteria({
      ...DEFAULT_FILTERS,
      q: "React",
      page: 9,
      view: "tiles",
      savedSearchId: 42,
    });
    expect(encoded.get("q")).toBe("React");
    expect(encoded.has("page")).toBe(false);
    expect(encoded.has("view")).toBe(false);
    expect(encoded.has("ss")).toBe(false);
  });

  it("saved-search API criteria omit pagination and presentation flags", () => {
    const criteria = filtersToApiCriteria({
      ...DEFAULT_FILTERS,
      q: "React",
      page: 9,
      view: "tiles",
      savedSearchId: 42,
    });
    expect(criteria.q).toBe("React");
    expect(criteria).not.toHaveProperty("page");
    expect(criteria).not.toHaveProperty("view");
    expect(criteria).not.toHaveProperty("savedSearchId");
    expect(criteria).not.toHaveProperty("include_match_stats");
  });

  it("treats 0 sentinel in addedByIds as 'system import'", () => {
    const decoded = decodeFilters(sp("added_by=0,12"));
    expect(decoded.addedByIds).toEqual([0, 12]);
  });

  it("encodes stage-move filters (who + date range) on distinct params", () => {
    const filters: CandidateFilters = {
      ...DEFAULT_FILTERS,
      stageMovedByIds: [4, 0],
      stageMovedAfter: "2026-05-01",
      stageMovedBefore: "2026-05-29",
    };
    const encoded = encodeFilters(filters);
    expect(encoded.get("stage_by")).toBe("4,0");
    expect(encoded.get("stage_from")).toBe("2026-05-01");
    expect(encoded.get("stage_to")).toBe("2026-05-29");
    expect(decodeFilters(encoded).stageMovedByIds).toEqual([4, 0]);
  });

  it("encodes stage-client + current-only on distinct params", () => {
    const filters: CandidateFilters = {
      ...DEFAULT_FILTERS,
      stageClientIds: [21, 33],
      stageCurrentOnly: true,
    };
    const encoded = encodeFilters(filters);
    expect(encoded.get("stage_client")).toBe("21,33");
    expect(encoded.get("stage_current")).toBe("1");
    const decoded = decodeFilters(encoded);
    expect(decoded.stageClientIds).toEqual([21, 33]);
    expect(decoded.stageCurrentOnly).toBe(true);
  });

  it("empty stage-client + off current-only stay out of the URL", () => {
    const encoded = encodeFilters({ ...DEFAULT_FILTERS });
    expect(encoded.has("stage_client")).toBe(false);
    expect(encoded.has("stage_current")).toBe(false);
  });

  it("rejects malformed stage dates so they never reach the API", () => {
    const decoded = decodeFilters(sp("stage_from=not-a-date&stage_to=2026-13-99x"));
    expect(decoded.stageMovedAfter).toBe("");
    expect(decoded.stageMovedBefore).toBe("");
  });

  it("empty stage-move filters stay out of the URL", () => {
    const encoded = encodeFilters({ ...DEFAULT_FILTERS });
    expect(encoded.has("stage_by")).toBe(false);
    expect(encoded.has("stage_from")).toBe(false);
    expect(encoded.has("stage_to")).toBe(false);
  });

  it("encodes the skill expression as skills_q and round-trips it", () => {
    const filters: CandidateFilters = {
      ...DEFAULT_FILTERS,
      skillsExpr: "Python AND React OR Vue -PHP",
    };
    const encoded = encodeFilters(filters);
    expect(encoded.get("skills_q")).toBe("Python AND React OR Vue -PHP");
    expect(decodeFilters(encoded).skillsExpr).toBe("Python AND React OR Vue -PHP");
  });

  it("reconstructs a skill expression from legacy skills/skill_combine URLs", () => {
    expect(decodeFilters(sp("skills=python,aws")).skillsExpr).toBe(
      "python AND aws",
    );
    expect(decodeFilters(sp("skills=python,aws&skill_combine=or")).skillsExpr).toBe(
      "python OR aws",
    );
    // skills_q wins over legacy params when both present.
    expect(
      decodeFilters(sp("skills_q=react&skills=python&skill_combine=or")).skillsExpr,
    ).toBe("react");
  });

  it("maps the skill expression to skill-scoped API params", () => {
    const params = filtersToApiParams(
      { ...DEFAULT_FILTERS, skillsExpr: "Python AND React OR Vue -PHP" },
      1,
    );
    expect(params.skills).toEqual(["Python"]);
    expect(params.skill_combine).toBeUndefined(); // single must term
    expect(params.skills_any).toEqual(["React|Vue"]);
    expect(params.skills_none).toEqual(["PHP"]);
  });

  it("maps open-to and recently changed jobs to API params", () => {
    const params = filtersToApiParams(
      {
        ...DEFAULT_FILTERS,
        openTo: ["expert_consult"],
        recentlyChangedJobs: 1,
      },
      1,
    );
    expect(params.open_to).toEqual(["expert_consult"]);
    expect(params.recently_changed_jobs).toBe(1);
  });

  it("sends lowercase skill_combine for multiple AND skills (no 422)", () => {
    const params = filtersToApiParams(
      { ...DEFAULT_FILTERS, skillsExpr: "Python AND React AND AWS" },
      1,
    );
    expect(params.skills).toEqual(["Python", "React", "AWS"]);
    expect(params.skill_combine).toBe("and");
  });

  it("filtersEqual compares independent of field order", () => {
    const a: CandidateFilters = { ...DEFAULT_FILTERS, q: "x", poolIds: [1, 2] };
    const b: CandidateFilters = { ...DEFAULT_FILTERS, poolIds: [1, 2], q: "x" };
    expect(filtersEqual(a, b)).toBe(true);
  });
});
