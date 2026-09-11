import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * C2 (the job page's full-search ranking) adds to the pipeline through the
 * bulk route it shares with manual search, the historical section and
 * quick-add. The backend can join the `add_to_pipeline` outcome to a ranking
 * only through the run the caller declares — so every add on this page must
 * carry the current full-search run. A dropped `run_id` breaks nothing on
 * screen; it silently turns every C2 add into an unattributed one.
 *
 * Reads the SOURCE: the page is a large client component whose render needs
 * the whole app shell, and the property is about which arguments the calls
 * carry, not about rendering.
 */
const PAGE = path.resolve(process.cwd(), "src/app/jobs/[id]/page.tsx");

describe("job page full-search adds declare their run", () => {
  const source = fs.readFileSync(PAGE, "utf-8");

  it("every bulk add on the page spreads the full-search origin", () => {
    const calls = [...source.matchAll(/proposalsBulkApi\.add\(([\s\S]*?)\)\s*;/g)];
    expect(calls.length).toBeGreaterThanOrEqual(2);
    for (const [, args] of calls) {
      expect(args).toContain("...fullSearchOrigin");
    }
  });

  it("the origin is the current run of this page's full search", () => {
    const origin = source.match(/const fullSearchOrigin = \{([\s\S]*?)\};/);
    expect(origin?.[1]).toContain("run_id: fullSearch.runId");
    expect(origin?.[1]).toContain('source: "full_search"');
  });
});
