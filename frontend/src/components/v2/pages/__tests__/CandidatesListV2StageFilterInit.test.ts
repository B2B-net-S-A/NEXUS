import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { decodeFilters } from "@/lib/url-filters";
import { PIPELINE_STAGE_OPTIONS } from "@/lib/filter-options";

const LIST = path.resolve(__dirname, "../CandidatesListV2.tsx");

describe("CandidatesListV2 — filtr etapu po odświeżeniu (posting)", () => {
  it("dekoder URL przyjmuje każdy etap oferowany w panelu, w tym „posting”", () => {
    const all = PIPELINE_STAGE_OPTIONS.map((o) => o.value);
    const decoded = decodeFilters(new URLSearchParams(`stage=${all.join(",")}`));
    expect(decoded.pipelineStage).toEqual(all);
    expect(decodeFilters(new URLSearchParams("stage=posting")).pipelineStage).toEqual([
      "posting",
    ]);
  });

  it("stan filtra etapu startuje z tego samego dekodera, nie z własnej listy etapów", () => {
    const source = fs.readFileSync(LIST, "utf8");
    const start = source.indexOf("const [pipelineStageFilter, setPipelineStageFilter]");
    expect(start).toBeGreaterThan(-1);
    const initializer = source.slice(start, source.indexOf(");", start) + 2);
    expect(initializer).toContain("decodeFilters(");
    expect(initializer).not.toContain('"withdrawn"');
  });
});
