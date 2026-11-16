import { describe, expect, it } from "vitest";
import { shortDate } from "@/lib/api/client-reports";
import { shiftMonth } from "../ReportsCalendarPanel";

describe("katalog raportów — formaty", () => {
  it("skraca datę w tym samym roku i dopisuje rok w innym", () => {
    expect(shortDate("2026-11-05", "2026-11")).toBe("05.11");
    expect(shortDate("2027-01-21", "2026-11")).toBe("21.01.2027");
    expect(shortDate(null)).toBe("—");
  });

  it("przesuwa miesiąc przez granicę roku", () => {
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-11", 0)).toBe("2026-11");
  });
});

describe("źródło wymogu", () => {
  it("pokazuje paragraf bez dublowania rodzaju, a bez paragrafu — skąd wpis", async () => {
    const { sourceText } = await import("../ClientReportsTab");
    expect(sourceText({ source_kind: "amendment", source_ref: "aneks 9, § 7 ust. 1b" })).toBe("aneks 9, § 7 ust. 1b");
    expect(sourceText({ source_kind: "contract", source_ref: null })).toBe("umowa ramowa");
    expect(sourceText({ source_kind: "dl", source_ref: "  " })).toBe("od Delivery Leada");
  });
});
