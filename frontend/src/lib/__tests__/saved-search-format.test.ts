import { describe, expect, it } from "vitest";

import { detectSavedSearchFormat } from "@/lib/saved-search-format";

describe("detectSavedSearchFormat", () => {
  it("detects the global-list payload by its qs string", () => {
    expect(
      detectSavedSearchFormat({ qs: "status=active&city=Warszawa", api: {} }),
    ).toBe("candidates_list");
    // even an empty querystring marks the list format
    expect(detectSavedSearchFormat({ qs: "" })).toBe("candidates_list");
  });

  it("detects a CandidateSearchRequest dump by its known keys", () => {
    expect(
      detectSavedSearchFormat({ q: "java", skills_must: ["Java"], sort: "relevance" }),
    ).toBe("search_request");
    expect(detectSavedSearchFormat({ rate_hourly_max: 150 })).toBe(
      "search_request",
    );
  });

  it("qs wins when both marker sets are present", () => {
    expect(detectSavedSearchFormat({ qs: "x=1", q: "java" })).toBe(
      "candidates_list",
    );
  });

  it("unknown for empty / malformed payloads", () => {
    expect(detectSavedSearchFormat({})).toBe("unknown");
    expect(detectSavedSearchFormat(null)).toBe("unknown");
    expect(detectSavedSearchFormat("qs=abc")).toBe("unknown");
    expect(detectSavedSearchFormat([1, 2])).toBe("unknown");
    expect(detectSavedSearchFormat({ foo: "bar" })).toBe("unknown");
  });
});
