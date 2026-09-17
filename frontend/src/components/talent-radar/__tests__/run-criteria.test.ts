import { describe, expect, it } from "vitest";

import {
  RADAR_BUDGET_ERROR,
  RADAR_OFFICE_DAYS_ERROR,
  formatRadarRunCriteria,
  isRadarRunCriteria,
  radarBudgetError,
  radarOfficeDaysError,
  type RadarRunCriteria,
} from "@/components/talent-radar/run-criteria";

describe("walidacja liczb Talent Radaru (limity backendu)", () => {
  it("budżet: puste i 0 to brak sufitu, powyżej 2000 lub nie-liczba to błąd", () => {
    expect(radarBudgetError("")).toBeNull();
    expect(radarBudgetError("0")).toBeNull();
    expect(radarBudgetError("2000")).toBeNull();
    expect(radarBudgetError("2001")).toBe(RADAR_BUDGET_ERROR);
    expect(radarBudgetError("-5")).toBe(RADAR_BUDGET_ERROR);
    expect(radarBudgetError("abc")).toBe(RADAR_BUDGET_ERROR);
  });

  it("dni w biurze: całkowite 0–7", () => {
    expect(radarOfficeDaysError("")).toBeNull();
    expect(radarOfficeDaysError("0")).toBeNull();
    expect(radarOfficeDaysError("7")).toBeNull();
    expect(radarOfficeDaysError("8")).toBe(RADAR_OFFICE_DAYS_ERROR);
    expect(radarOfficeDaysError("2.5")).toBe(RADAR_OFFICE_DAYS_ERROR);
  });
});

const CRITERIA: RadarRunCriteria = {
  clientName: "Acme",
  budget: 150,
  location: "Warszawa",
  officeDays: 2,
  officeLocation: "Kraków",
  excludeRemoteOnly: true,
};

describe("kryteria biegu", () => {
  it("formatuje klienta, budżet, lokalizację i dni", () => {
    expect(formatRadarRunCriteria(CRITERIA)).toBe(
      "Klient: Acme · budżet do 150 PLN/h · lokalizacja: Warszawa · biuro 2 dni/tydz. (Kraków) · bez „wyłącznie zdalnie”",
    );
  });

  it("budżet z odpowiedzi przeglądu wygrywa, brak budżetu to „bez sufitu”", () => {
    expect(formatRadarRunCriteria(CRITERIA, 180)).toContain("budżet do 180 PLN/h");
    expect(
      formatRadarRunCriteria({ ...CRITERIA, budget: null, officeDays: 0, excludeRemoteOnly: false }),
    ).toBe("Klient: Acme · bez sufitu stawki · lokalizacja: Warszawa · tylko zdalnie");
  });

  it("strażnik kształtu odrzuca obce obiekty", () => {
    expect(isRadarRunCriteria(CRITERIA)).toBe(true);
    expect(isRadarRunCriteria({ ...CRITERIA, budget: "150" })).toBe(false);
    expect(isRadarRunCriteria(null)).toBe(false);
  });
});
