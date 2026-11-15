import { describe, expect, it } from "vitest";

import type { FrameworkOverviewRow } from "@/lib/api/framework-rates";
import { filterRows, inRateShare, quarterLabel } from "@/lib/framework-overview";

const row = (person: string, status: FrameworkOverviewRow["status"], category: string | null): FrameworkOverviewRow => ({
  contract_id: 1, person, category, source: null, coa_label: null, rate: null, limit: null, base: null,
  addon: null, status, gap: null, order_end: null, levers: [], limit_mismatch: false,
});

describe("zakładka Stawki ramowe", () => {
  it("filtruje po statusie i szuka po osobie albo kategorii", () => {
    const rows = [row("Ola Testowa", "over", "IT Developer - Senior"), row("Jan Próbny", "in", "IT Architect")];
    expect(filterRows(rows, "over", "").map((r) => r.person)).toEqual(["Ola Testowa"]);
    expect(filterRows(rows, "all", "architect").map((r) => r.person)).toEqual(["Jan Próbny"]);
    expect(filterRows(rows, "all", "PRÓBNY").map((r) => r.person)).toEqual(["Jan Próbny"]);
  });

  it("liczy udział w stawce tylko wśród osób z limitem", () => {
    expect(inRateShare({ in: 6, in_addon: 2, over: 2, no_limit: 40 })).toBe(80);
    expect(inRateShare({ in: 0, in_addon: 0, over: 0, no_limit: 3 })).toBeNull();
  });

  it("nazywa kwartał po ostatnim dniu", () => {
    expect(quarterLabel("2026-09-30", "2026-11-15")).toBe("Q3 2026");
    expect(quarterLabel("2025-12-31", "2026-11-15")).toBe("Q4 2025");
    expect(quarterLabel("2026-11-15", "2026-11-15")).toBe("dziś");
  });
});
