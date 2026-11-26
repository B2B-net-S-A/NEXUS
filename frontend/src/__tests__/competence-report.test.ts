import { describe, expect, it } from "vitest";

import {
  EMPTY_STATE,
  addCity,
  buildPayload,
  formatSentDay,
  needsOffice,
  parseWholeRate,
  stateFromConditions,
  toggleCity,
  toggleMode,
  type ConditionsState,
  type ReportConditions,
} from "@/lib/competence-report";

const FILLED: ConditionsState = {
  ...EMPTY_STATE,
  rate: "180",
  contract: "b2b",
  modes: ["hybrid"],
  officeDays: "2",
  cities: ["Kraków"],
  start: "1m",
};

describe("warunki z maila z raportem kompetencji", () => {
  it("mapuje formularz na ciało żądania jak strona", () => {
    const { payload, errors } = buildPayload({ ...FILLED, currentRate: " 150 ", cities: [" Kraków ", "kraków", "Łódź"] });
    expect(errors).toEqual({});
    expect(payload).toEqual({
      rate: 180,
      current_rate: 150,
      contract: "b2b",
      modes: ["hybrid"],
      office_days_max: 2,
      office_cities: ["Kraków", "Łódź"],
      start: "1m",
    });
  });

  it("przy samej pracy zdalnej nie pyta o dni i miasta i ich nie wysyła", () => {
    expect(needsOffice(["remote"])).toBe(false);
    expect(needsOffice(["remote", "hybrid"])).toBe(true);
    const { payload, errors } = buildPayload({ ...FILLED, modes: ["remote"], officeDays: "", cities: ["Gdańsk"] });
    expect(errors).toEqual({});
    expect(payload?.office_days_max).toBeNull();
    expect(payload?.office_cities).toEqual([]);
  });

  it("dni w biurze 0 to poprawna odpowiedź", () => {
    expect(buildPayload({ ...FILLED, officeDays: "0" }).payload?.office_days_max).toBe(0);
  });

  it("odmawia pustych i złych pól", () => {
    const { payload, errors } = buildPayload({ ...EMPTY_STATE, modes: ["onsite"], currentRate: "abc" });
    expect(payload).toBeNull();
    expect(Object.keys(errors).sort()).toEqual(
      ["cities", "contract", "currentRate", "officeDays", "rate", "start"].sort(),
    );
    expect(buildPayload({ ...FILLED, modes: [] }).errors.modes).toBeTruthy();
    expect(buildPayload({ ...FILLED, rate: "2001" }).errors.rate).toBeTruthy();
    expect(buildPayload({ ...FILLED, officeDays: "6" }).errors.officeDays).toBeTruthy();
  });

  it("czyta stawkę jako liczbę całkowitą 1–2000", () => {
    expect(parseWholeRate("1 500")).toBe(1500);
    expect(parseWholeRate("0")).toBeNull();
    expect(parseWholeRate("150,5")).toBeNull();
    expect(parseWholeRate("2001")).toBeNull();
  });

  it("odtwarza stan z zapisanych warunków", () => {
    const saved: ReportConditions = {
      rate: 200,
      current_rate: null,
      contract: "any",
      modes: ["onsite", "remote"],
      office_days_max: 0,
      office_cities: ["Wrocław"],
      start: "browsing",
    };
    const state = stateFromConditions(saved);
    expect(state).toMatchObject({ rate: "200", currentRate: "", officeDays: "0", modes: ["remote", "onsite"] });
    expect(buildPayload(state).payload).toEqual({ ...saved, modes: ["remote", "onsite"] });
  });

  it("tryby i miasta przełącza bez powtórek, do 10 miast", () => {
    expect(toggleMode(["onsite"], "remote")).toEqual(["remote", "onsite"]);
    expect(toggleMode(["remote", "onsite"], "remote")).toEqual(["onsite"]);
    expect(addCity([], " kraków ")).toEqual(["Kraków"]);
    expect(toggleCity(["Kraków"], "kraków")).toEqual([]);
    const ten = Array.from({ length: 10 }, (_, i) => `Miasto ${i}`);
    expect(addCity(ten, "Katowice")).toEqual(ten);
  });

  it("pokazuje dzień wysyłki po polsku", () => {
    expect(formatSentDay("2026-11-25")).toBe("25 listopada");
  });
});
