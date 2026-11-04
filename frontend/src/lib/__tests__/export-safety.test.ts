import { describe, expect, it } from "vitest";

import { safeSpreadsheetCell } from "@/lib/export-safety";

// Runda 6 audytu (G1): CSV budowany w przeglądarce (eksport Insights) nie
// chronił przed formułą — lustro `backend/app/core/export_safety.safe_cell`.
describe("safeSpreadsheetCell", () => {
  it.each(["=HYPERLINK(\"http://x\")", "+SUM(A1)", "-cmd", "@SUM(A1)", "\tx", "\rx"])(
    "dopisuje apostrof przed formułą: %j",
    (value) => {
      expect(safeSpreadsheetCell(value)).toBe(`'${value}`);
    },
  );

  it.each(["+48 600 100 200", "-1 200,50", "+48 (22) 123-45-67"])(
    "zostawia telefon i kwotę: %j",
    (value) => {
      expect(safeSpreadsheetCell(value)).toBe(value);
    },
  );

  it("liczby, puste i zwykły tekst przechodzą bez zmian", () => {
    expect(safeSpreadsheetCell(-5)).toBe(-5);
    expect(safeSpreadsheetCell(null)).toBeNull();
    expect(safeSpreadsheetCell(undefined)).toBeUndefined();
    expect(safeSpreadsheetCell("Anna")).toBe("Anna");
    expect(safeSpreadsheetCell("=5")).toBe("'=5");
  });
});
