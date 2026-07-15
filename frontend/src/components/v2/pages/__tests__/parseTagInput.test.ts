import { describe, expect, it } from "vitest";

import { parseTagInput } from "@/components/v2/pages/CandidateSearchView";

describe("parseTagInput", () => {
  it("splits on commas and trims", () => {
    expect(parseTagInput("linkedin, pilne ,  senior")).toEqual([
      "linkedin",
      "pilne",
      "senior",
    ]);
  });

  it("splits on newlines too", () => {
    expect(parseTagInput("a\nb,c")).toEqual(["a", "b", "c"]);
  });

  it("drops blanks and dedupes case-insensitively", () => {
    expect(parseTagInput("Java, , java,  JAVA , react")).toEqual([
      "Java",
      "react",
    ]);
  });

  it("returns [] for empty input", () => {
    expect(parseTagInput("")).toEqual([]);
    expect(parseTagInput("  , , ")).toEqual([]);
  });

  it("caps at 20 tags", () => {
    const raw = Array.from({ length: 30 }, (_, i) => `t${i}`).join(",");
    expect(parseTagInput(raw)).toHaveLength(20);
  });
});
