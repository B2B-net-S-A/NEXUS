import { describe, expect, it } from "vitest";

import { tooltipValue } from "@/components/v2/dashboard/custom/MetricTileBody";

describe("tooltipValue (FE-N10)", () => {
  it("brak wartości to „—”, nie zero", () => {
    expect(tooltipValue(null, "count")).toBe("—");
    expect(tooltipValue(undefined, "pln")).toBe("—");
    expect(tooltipValue("", "pln")).toBe("—");
    expect(tooltipValue("abc", "count")).toBe("—");
  });

  it("liczba formatuje się jak dotąd", () => {
    expect(tooltipValue(0, "count")).toBe("0");
    expect(tooltipValue(1200, "pln")).toMatch(/^1\s?200 zł$/);
  });
});
