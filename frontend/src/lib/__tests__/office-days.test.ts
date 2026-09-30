import { describe, expect, it } from "vitest";

import cases from "@/lib/__fixtures__/office-days-cases.json";
import {
  officeDaysFields,
  officeDaysFormValue,
  officeDaysLabel,
  parseOfficeDaysInput,
  weeklyFromMonthly,
} from "@/lib/office-days";

describe("office-days — lustro backend/app/services/office_days.py", () => {
  it.each(cases.weekly_from_monthly)(
    "$month dni w miesiącu → $week w tygodniu",
    ({ month, week }) => {
      expect(weeklyFromMonthly(month)).toBe(week);
    },
  );

  it.each(cases.label)("etykieta $week/$month", ({ week, month, label }) => {
    expect(officeDaysLabel(week, month)).toBe(label);
  });

  it("wpis miesięczny nigdy nie czyta się jak praca zdalna", () => {
    for (let m = 1; m <= 22; m++) expect(weeklyFromMonthly(m)).toBeGreaterThanOrEqual(1);
  });
});

describe("officeDaysFields", () => {
  it("miesięcznie przy hybrydzie daje oba pola", () => {
    expect(officeDaysFields("2", "month", "hybrid")).toEqual({
      onsite_days_per_week: 1,
      onsite_days_per_month: 2,
    });
  });

  it("tygodniowo czyści pole miesięczne", () => {
    expect(officeDaysFields("3", "week", "onsite")).toEqual({
      onsite_days_per_week: 3,
      onsite_days_per_month: null,
    });
  });

  it("miesięcznie poza hybrydą jest brakiem, nie zgadywaniem", () => {
    expect(officeDaysFields("2", "month", "onsite")).toEqual({
      onsite_days_per_week: null,
      onsite_days_per_month: null,
    });
  });

  it("zakresy: tydzień 0–7, miesiąc 1–22", () => {
    expect(parseOfficeDaysInput("0", "week")).toBe(0);
    expect(parseOfficeDaysInput("8", "week")).toBeNull();
    expect(parseOfficeDaysInput("0", "month")).toBeNull();
    expect(parseOfficeDaysInput("22", "month")).toBe(22);
    expect(parseOfficeDaysInput("1.5", "month")).toBeNull();
  });

  it("stan formularza z zapisanej pary", () => {
    expect(officeDaysFormValue(1, 2)).toEqual({ value: "2", period: "month" });
    expect(officeDaysFormValue(3, null)).toEqual({ value: "3", period: "week" });
    expect(officeDaysFormValue(null, null)).toEqual({ value: "", period: "week" });
  });
});
