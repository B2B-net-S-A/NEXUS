import { describe, expect, it } from "vitest";

import cases from "@/lib/__fixtures__/recruitment-rate-check-cases.json";
import {
  compareRates,
  formatRecruitmentRate,
  hourlyPln,
} from "@/lib/recruitment-rate-check";
import {
  contractRateNote,
  lineRevenueWarning,
  recruitmentRateLine,
  recruitmentRateNotes,
} from "@/lib/recruitment-rate-hint";
import type { RecruitmentRate } from "@/lib/api/recruitmentRates";

// Te same przypadki czyta `backend/tests/test_recruitment_rate_check.py`.
describe("reguła porównania stawek z rekrutacji — lustro backendu", () => {
  it.each(cases.compare)("$name", (c) => {
    expect(compareRates(c.reference, c.actual)).toBe(c.expected);
  });

  it.each(cases.hourly)("PLN/h z $value $unit $currency", (c) => {
    const got = hourlyPln(c.value, c.unit, c.currency);
    expect(got).toBe(c.expected === null ? null : Number(c.expected));
  });

  it.each(cases.format)("format $value $unit", (c) => {
    expect(formatRecruitmentRate(c.value, c.unit)).toBe(c.expected);
  });
});

const RATE: RecruitmentRate = {
  candidate_id: 1,
  job_id: 7,
  job_title: "Java Developer",
  client_rate_value: 165,
  client_rate_unit: "hourly",
  client_rate_currency: "PLN",
  client_rate_at: null,
  client_rate_by_name: "Anna Lead",
  client_rate_redacted: false,
  candidate_rate_value: 140,
  candidate_rate_unit: "hourly",
  candidate_rate_currency: "PLN",
  candidate_rate_at: null,
};

describe("podpowiedzi „Z rekrutacji…”", () => {
  it("linia niesie rekrutację, osobę i obie stawki", () => {
    expect(recruitmentRateLine(RATE)).toBe(
      "Z rekrutacji „Java Developer” (Anna Lead): 165 zł/h · kandydat 140 zł/h",
    );
  });

  it("zredagowana stawka do klienta znika z linii", () => {
    expect(
      recruitmentRateLine({
        ...RATE,
        client_rate_value: null,
        client_rate_by_name: null,
        client_rate_redacted: true,
      }),
    ).toBe("Z rekrutacji „Java Developer”: kandydat 140 zł/h");
  });

  it("notka tylko przy różnicy, MD liczy się jako 8 godzin", () => {
    expect(
      recruitmentRateNotes(RATE, {
        revenue: { value: "1320", unit: "daily", currency: "PLN" },
        cost: { value: "140", unit: "hourly", currency: "PLN" },
      }),
    ).toEqual([]);
    const notes = recruitmentRateNotes(RATE, {
      revenue: { value: "170", unit: "hourly", currency: "PLN" },
      cost: { value: "150", unit: "hourly", currency: "PLN" },
    });
    expect(notes).toHaveLength(2);
    expect(notes[0]).toMatch(/popraw stawkę do klienta w rekrutacji/);
  });

  it("ostrzeżenie karty MD pokazuje przeliczenie × 8", () => {
    expect(lineRevenueWarning(RATE, { value: "1350", unit: "md", currency: "PLN" })).toBe(
      "Stawka przychodowa różni się od stawki do klienta z rekrutacji „Java Developer” (165 zł/h × 8 = 1320 zł/MD) — sprawdź. Zapis nie jest blokowany.",
    );
    expect(lineRevenueWarning(RATE, { value: "1320", unit: "md", currency: "PLN" })).toBeNull();
    // Inna waluta — nieporównywalne, bez ostrzeżenia.
    expect(lineRevenueWarning(RATE, { value: "300", unit: "md", currency: "EUR" })).toBeNull();
  });

  it("notka generatora dla pierwszego etapu w PLN", () => {
    const recruitment = { value: 140, unit: "hourly", currency: "PLN", job_title: "Java Developer" };
    expect(contractRateNote(recruitment, "140", "PLN")).toBeNull();
    expect(contractRateNote(recruitment, "", "PLN")).toBeNull();
    expect(contractRateNote(recruitment, "150", "EUR")).toBeNull();
    expect(contractRateNote(recruitment, "150", "PLN")).toMatch(
      /Stawka kandydata z rekrutacji „Java Developer”: 140 zł\/h/,
    );
  });
});
