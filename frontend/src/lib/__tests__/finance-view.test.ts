import { describe, expect, it } from "vitest";

import { parseFinanceView } from "@/lib/finance-view";

describe("parseFinanceView (FE-N09)", () => {
  it("zna wszystkie widoki, reszta to wyniki", () => {
    expect(parseFinanceView("order-pdfs")).toBe("order-pdfs");
    expect(parseFinanceView("md")).toBe("md");
    expect(parseFinanceView(null)).toBe("results");
    expect(parseFinanceView("bogus")).toBe("results");
  });
});
