import { describe, expect, it } from "vitest";
import {
  defaultPlacementsRange,
  placementsExportFilename,
  placementsRangeError,
} from "@/lib/placements-export";

describe("defaultPlacementsRange", () => {
  it("covers the whole current month", () => {
    expect(defaultPlacementsRange("2026-10-23")).toEqual({
      from: "2026-10-01",
      to: "2026-10-31",
    });
  });

  it("knows short months and leap years", () => {
    expect(defaultPlacementsRange("2028-02-10").to).toBe("2028-02-29");
    expect(defaultPlacementsRange("2026-02-10").to).toBe("2026-02-28");
    expect(defaultPlacementsRange("2026-11-30").to).toBe("2026-11-30");
  });
});

describe("placementsRangeError", () => {
  it("accepts a one-day range", () => {
    expect(placementsRangeError({ from: "2026-10-01", to: "2026-10-01" })).toBeNull();
  });

  it("refuses a reversed range with the same words as the server", () => {
    expect(placementsRangeError({ from: "2026-10-31", to: "2026-10-01" })).toBe(
      "Data „do” jest wcześniejsza niż „od”.",
    );
  });

  it("asks for both dates", () => {
    expect(placementsRangeError({ from: "", to: "2026-10-01" })).toBe("Podaj obie daty.");
    expect(placementsRangeError({ from: "2026-10-01", to: "" })).toBe("Podaj obie daty.");
  });
});

it("names the file after the range", () => {
  expect(placementsExportFilename({ from: "2026-10-01", to: "2026-10-31" })).toBe(
    "placementy-2026-10-01-2026-10-31.xlsx",
  );
});
