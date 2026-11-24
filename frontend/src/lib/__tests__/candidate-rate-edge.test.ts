import { describe, expect, it } from "vitest";

import {
  dayText,
  declaredFromText,
  hourlyText,
  monthYear,
  rateFromContextLine,
  rateFromText,
  rateReasonLabel,
  rateSecondLine,
  rateSourceLabel,
  thisJobRateText,
  toAmount,
} from "@/lib/candidate-rate";

describe("toAmount / hourlyText", () => {
  it("brak, pusty napis, zero, ujemna i tekst to brak stawki", () => {
    for (const v of [null, undefined, "", 0, "0", -5, "abc", Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(toAmount(v)).toBeNull();
      expect(hourlyText(v)).toBeNull();
    }
  });
  it("tekst liczbowy z API i grosze zaokrąglone do dwóch miejsc", () => {
    expect(toAmount("125.19")).toBe(125.19);
    expect(hourlyText("125.199")).toBe("125,2 zł/h");
    expect(hourlyText(80)).toBe("80 zł/h");
  });
});

describe("daty w kalendarzu Europe/Warsaw", () => {
  it("31.12 23:30 UTC to już styczeń następnego roku w Warszawie", () => {
    expect(monthYear("2026-12-31T23:30:00Z")).toBe("01.2027");
    expect(dayText("2026-12-31T23:30:00Z")).toBe("01.01.2027");
  });
  it("brak i niepoprawna data: null", () => {
    expect(monthYear(null)).toBeNull();
    expect(monthYear("nie-data")).toBeNull();
    expect(dayText(undefined)).toBeNull();
    expect(dayText("")).toBeNull();
  });
});

describe("rateFromText", () => {
  it("bez stawki: null", () => {
    expect(rateFromText({ rate_from_hourly: null })).toBeNull();
  });
  it("nieaktualna z rokiem i bez daty", () => {
    expect(rateFromText({ rate_from_hourly: 80, rate_from_stale: true, rate_from_at: "2024-06-01" })).toBe(
      "od 80 zł/h · z 2024",
    );
    expect(rateFromText({ rate_from_hourly: 80, rate_from_stale: true })).toBe(
      "od 80 zł/h · nieaktualna",
    );
    expect(rateFromText({ rate_from_hourly: 80, rate_from_stale: true, rate_from_at: "zła" })).toBe(
      "od 80 zł/h · nieaktualna",
    );
  });
});

describe("declaredFromText", () => {
  it("źródło inne niż umowa: null", () => {
    expect(
      declaredFromText({ rate_from_source: "profile", rate_from_hourly: 100, rate_declared_from_hourly: 90 }),
    ).toBeNull();
  });
  it("brak którejś stawki albo deklaracja nie niższa (w granicy pół grosza): null", () => {
    expect(declaredFromText({ rate_from_source: "contract", rate_from_hourly: 100 })).toBeNull();
    expect(declaredFromText({ rate_from_source: "contract", rate_declared_from_hourly: 90 })).toBeNull();
    expect(
      declaredFromText({ rate_from_source: "contract", rate_from_hourly: 100, rate_declared_from_hourly: 99.996 }),
    ).toBeNull();
    expect(
      declaredFromText({ rate_from_source: "contract", rate_from_hourly: 100, rate_declared_from_hourly: 110 }),
    ).toBeNull();
  });
  it("niższa deklaracja z miesiącem i bez", () => {
    expect(
      declaredFromText({
        rate_from_source: "contract",
        rate_from_hourly: "100",
        rate_declared_from_hourly: "90",
        rate_declared_from_at: "2026-10-15T10:00:00Z",
      }),
    ).toBe("zadeklarowana od 90 zł/h (10.2026)");
    expect(
      declaredFromText({ rate_from_source: "contract", rate_from_hourly: 100, rate_declared_from_hourly: 99.99 }),
    ).toBe("zadeklarowana od 99,99 zł/h");
  });
});

describe("rateSecondLine", () => {
  it("brak którejś stawki albo różnica poniżej pół grosza: null", () => {
    expect(rateSecondLine({ rate_from_hourly: 100 })).toBeNull();
    expect(rateSecondLine({ rate_latest_hourly: 100 })).toBeNull();
    expect(rateSecondLine({ rate_from_hourly: 100, rate_latest_hourly: 100.004 })).toBeNull();
  });
  it("bez daty i liczby obserwacji: sama kwota", () => {
    expect(rateSecondLine({ rate_from_hourly: 100, rate_latest_hourly: 140 })).toBe("ostatnio 140 zł/h");
  });
  it("jedna obserwacja nie dopisuje licznika, kilka — tak", () => {
    expect(
      rateSecondLine({ rate_from_hourly: 100, rate_latest_hourly: 140, rate_observation_count: 1 }),
    ).toBe("ostatnio 140 zł/h");
    expect(
      rateSecondLine({
        rate_from_hourly: 100,
        rate_latest_hourly: 140,
        rate_latest_at: "2026-06-10T10:00:00Z",
        rate_observation_count: 5,
      }),
    ).toBe("ostatnio 140 zł/h (06.2026) · 5 stawek");
  });
});

describe("thisJobRateText / rateFromContextLine", () => {
  it("rekrutacja bez stawki: nie pytano", () => {
    expect(thisJobRateText(0)).toBe("W tej rekrutacji: nie pytano");
    expect(thisJobRateText("135")).toBe("W tej rekrutacji: 135 zł/h");
  });
  it("kontekst: null, zerowa kwota, bez roli i daty, nieaktualna", () => {
    expect(rateFromContextLine(null)).toBeNull();
    expect(rateFromContextLine({ amount: 0, at: null, job_title: null })).toBeNull();
    expect(rateFromContextLine({ amount: 80, at: null, job_title: null })).toBe("Stawka od 80 zł/h");
    expect(rateFromContextLine({ amount: 80, at: "zła", job_title: null, stale: true })).toBe(
      "Stawka od 80 zł/h (nieaktualna)",
    );
    expect(
      rateFromContextLine({ amount: "80", at: "2025-08-10T10:00:00Z", job_title: null, stale: true }),
    ).toBe("Stawka od 80 zł/h (nieaktualna) · 08.2025");
  });
});

describe("rateSourceLabel / rateReasonLabel", () => {
  it("brak źródła, znane, nieznane z profilu i obce", () => {
    expect(rateSourceLabel(null)).toBe("Nieznane źródło");
    expect(rateSourceLabel("")).toBe("Nieznane źródło");
    expect(rateSourceLabel("contract")).toBe("Umowa u nas (bieżąca)");
    expect(rateSourceLabel("profile_cos_nowego")).toBe("Profil");
    expect(rateSourceLabel("import_x")).toBe("import_x");
  });
  it("każdy powód i domyślny", () => {
    expect(rateReasonLabel("minimum")).toBe("liczy się jako minimum");
    expect(rateReasonLabel("counts")).toBe("liczy się");
    expect(rateReasonLabel("excluded")).toBe("wyłączona z minimum");
    expect(rateReasonLabel("excluded", "Anna Przykładowa")).toBe("wyłączona przez: Anna Przykładowa");
    expect(rateReasonLabel("outside_window")).toBe("starsza niż 18 miesięcy");
    expect(rateReasonLabel("superseded")).toBe("niższa niż późniejsze minimum");
    expect(rateReasonLabel("contract")).toBe("pracuje u nas — liczy się umowa");
    expect(rateReasonLabel("eur")).toBe("inna waluta lub jednostka");
  });
});
