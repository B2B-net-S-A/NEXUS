import { describe, expect, it } from "vitest";

import type { ParamCatalogItem } from "@/lib/api/payroll-lists";

import {
  changedParams,
  companyMissing,
  nextMonth,
  paramField,
  paramGroups,
  paramProblems,
  paramText,
  paramValue,
} from "../parameters-model";

const CATALOG: ParamCatalogItem[] = [
  { key: "pension_employee_rate", label: "Emerytalna — pracownik", group: "ZUS", unit: "%", min: "0", max: "30", integer: "0" },
  { key: "annual_pension_limit", label: "Roczny limit", group: "ZUS", unit: "zł", min: "1000", max: "10000000", integer: "0" },
  { key: "pit_rate_low", label: "Skala PIT — pierwsza stawka", group: "PIT", unit: "%", min: "0", max: "50", integer: "0" },
  { key: "pit_rate_high", label: "Skala PIT — druga stawka", group: "PIT", unit: "%", min: "0", max: "60", integer: "0" },
  { key: "youth_age", label: "Ulga dla młodych — do ukończenia", group: "Wiek", unit: "lat", min: "18", max: "40", integer: "1" },
];

const CURRENT = {
  pension_employee_rate: "9.76",
  annual_pension_limit: "282600.00",
  pit_rate_low: "12",
  pit_rate_high: "32",
  youth_age: "26",
};

describe("parametry płac", () => {
  it("pokazuje wartości z jednostką po polsku", () => {
    expect(paramText("9.76", "%")).toBe("9,76%");
    expect(paramText("282600.00", "zł")).toBe("282 600,00 zł");
    expect(paramText("26", "lat")).toBe("26 lat");
    expect(paramText(null, "%")).toBe("—");
    expect(paramField("2.50")).toBe("2,5");
    expect(paramValue("282 600,5")).toBe("282600.5");
  });

  it("grupuje katalog w kolejności z serwera", () => {
    expect(paramGroups(CATALOG).map((group) => [group.group, group.items.length])).toEqual([
      ["ZUS", 2],
      ["PIT", 2],
      ["Wiek", 1],
    ]);
  });

  it("sprawdza liczbę, zakres, całkowitą i kolejność stawek PIT jak serwer", () => {
    const values = Object.fromEntries(Object.entries(CURRENT).map(([key, value]) => [key, paramField(value)]));
    expect(paramProblems(CATALOG, values)).toEqual([]);
    expect(
      paramProblems(CATALOG, { ...values, pension_employee_rate: "abc", youth_age: "26,5", pit_rate_high: "10", annual_pension_limit: "5" }),
    ).toEqual([
      "Emerytalna — pracownik: podaj liczbę.",
      "Roczny limit: od 1000 do 10000000 zł.",
      "Ulga dla młodych — do ukończenia: liczba całkowita.",
      "Druga stawka skali PIT nie może być niższa od pierwszej.",
    ]);
  });

  it("liczy zmienione parametry względem obowiązującej wersji", () => {
    const values = { ...CURRENT, pension_employee_rate: "9,80", annual_pension_limit: "282 600" };
    expect(changedParams(CATALOG, CURRENT, values).map((item) => item.key)).toEqual(["pension_employee_rate"]);
  });

  it("podpowiada następny miesiąc i braki płatnika", () => {
    expect(nextMonth("2026-11-14")).toBe("2026-12");
    expect(nextMonth("2026-12-01")).toBe("2027-01");
    expect(companyMissing({ missing: ["regon", "tax_office_code"] })).toBe("REGON, kod urzędu skarbowego");
  });
});
