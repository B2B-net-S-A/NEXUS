import { describe, expect, it } from "vitest";
import { previousMonth } from "@/lib/previous-month";

describe("previousMonth", () => {
  it("daje pełny poprzedni miesiąc", () => {
    expect(previousMonth("2026-11-09")).toEqual({
      key: "2026-10",
      from: "2026-10-01",
      to: "2026-10-31",
    });
  });

  it("w styczniu cofa rok", () => {
    expect(previousMonth("2027-01-15").key).toBe("2026-12");
  });

  it("zna luty w roku przestępnym", () => {
    expect(previousMonth("2028-03-01").to).toBe("2028-02-29");
  });
});
