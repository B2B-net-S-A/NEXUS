import { describe, expect, it } from "vitest";

import {
  EMPTY_STATE,
  addCity,
  buildPayload,
  hourlyRate,
  parseAmount,
  rateSummary,
  stateFromAnswers,
  unitHint,
} from "@/lib/candidate-terms";

describe("formularz warunków kandydata", () => {
  it("czyta kwoty jak ludzie: spacje i przecinek", () => {
    expect(parseAmount("18 500")).toBe(18500);
    expect(parseAmount("95,5")).toBe(95.5);
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("sto")).toBeNaN();
  });

  it("dzieli stawkę miesięczną przez 168 h", () => {
    expect(hourlyRate(20160, "month")).toBe(120);
    expect(hourlyRate(120, "hour")).toBe(120);
  });

  it("podpowiada jednostkę przy kwocie nie od tej jednostki", () => {
    expect(unitHint(25000, "hour")).toBe("looks_monthly");
    expect(unitHint(150, "month")).toBe("looks_hourly");
    expect(unitHint(120, "hour")).toBeNull();
  });

  it("odrzuca pusty formularz", () => {
    expect(buildPayload(EMPTY_STATE).errors).toEqual(["empty"]);
  });

  it("odrzuca stawkę poza 20–1000 zł/h po przeliczeniu", () => {
    const { errors } = buildPayload({ ...EMPTY_STATE, rateAmount: "1500", rateUnit: "hour" });
    expect(errors).toEqual(["rate_range"]);
    const ok = buildPayload({ ...EMPTY_STATE, rateAmount: "20160", rateUnit: "month" });
    expect(ok.errors).toEqual([]);
    expect(ok.payload.rate).toEqual({ amount: "20160", unit: "month", currency: "PLN" });
  });

  it("dni w biurze tylko przy hybrydzie, miasta tylko gdy biuro wchodzi w grę", () => {
    const remote = buildPayload({
      ...EMPTY_STATE,
      modes: ["remote"],
      onsiteDays: 3,
      cities: ["Gdańsk"],
    });
    expect(remote.payload.onsite_days).toBeUndefined();
    expect(remote.payload.cities).toEqual([]);
    const hybrid = buildPayload({
      ...EMPTY_STATE,
      modes: ["hybrid", "remote"],
      onsiteDays: 2,
      cities: ["Gdańsk"],
    });
    expect(hybrid.payload.modes).toEqual(["remote", "hybrid"]);
    expect(hybrid.payload.onsite_days).toBe(2);
    expect(hybrid.payload.cities).toEqual(["Gdańsk"]);
  });

  it("okres wypowiedzenia dłuższy niż 6 miesięcy to błąd", () => {
    const bad = buildPayload({ ...EMPTY_STATE, startKind: "notice", noticeValue: "9" });
    expect(bad.errors).toEqual(["start"]);
    const good = buildPayload({ ...EMPTY_STATE, startKind: "notice", noticeValue: "1" });
    expect(good.payload.start).toEqual({ kind: "notice", value: 1, unit: "months" });
  });

  it("miasta bez duplikatów i najwyżej pięć", () => {
    let cities: string[] = [];
    for (const c of ["Gdańsk", "gdańsk", " Gdynia ", "Łódź", "Kraków", "Katowice", "Poznań"]) {
      cities = addCity(cities, c);
    }
    expect(cities).toEqual(["Gdańsk", "Gdynia", "Łódź", "Kraków", "Katowice"]);
  });

  it("ponowne wejście odtwarza ostatnią odpowiedź", () => {
    const state = stateFromAnswers({
      rate: { amount: "120", unit: "hour", currency: "PLN" },
      modes: ["hybrid", "bogus"],
      onsite_days: 2,
      cities: ["Gdańsk"],
      start: { kind: "notice", date: null, value: 1, unit: "months" },
      future_consent: true,
    });
    expect(state.modes).toEqual(["hybrid"]);
    expect(state.noticeValue).toBe("1");
    expect(state.futureConsent).toBe(true);
    expect(rateSummary(state, "pl")).toBe("120 PLN za godzinę");
  });
});
