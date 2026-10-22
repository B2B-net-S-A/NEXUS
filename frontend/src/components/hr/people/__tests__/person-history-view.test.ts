import { describe, expect, it } from "vitest";

import type { PersonTimesheetMonth } from "@/lib/api/hr-person-history";

import {
  hoursOfNorm,
  poolSummary,
  previousPeopleList,
  timesheetStatus,
} from "../person-history-view";

const month = (partial: Partial<PersonTimesheetMonth> = {}): PersonTimesheetMonth => ({
  year: 2026,
  month: 9,
  timesheet_id: 1,
  status: "approved",
  hours: 167.5,
  norm_hours: 176,
  has_pdf: true,
  ...partial,
});

describe("linia puli w „Nieobecnościach <rok>”", () => {
  const ring = { pool: 28, used: 16.5, planned: 3, remaining: 8.5, usedPct: 0, plannedPct: 0 };

  it("saldo z serwera: pula, wykorzystane, zaplanowane, zostało — bez słowa „urlop”", () => {
    const line = poolSummary({ form: "b2b", ring, entitlement: undefined, year: 2026 });
    expect(line).toBe("Pula 28 dni · wykorzystane 16,5 · zaplanowane 3 · zostało 8,5");
    expect(line).not.toMatch(/urlop/i);
    expect(
      poolSummary({ form: null, ring: { ...ring, planned: 0 }, entitlement: undefined, year: 2026 }),
    ).toBe("Pula 28 dni · wykorzystane 16,5 · zostało 8,5");
  });

  it("zlecenie bez puli; bez salda — wiersz Kadr albo „nie jest ustawiona”", () => {
    expect(poolSummary({ form: "zlecenie", ring, entitlement: undefined, year: 2026 })).toMatch(
      /^Na umowie zlecenie nie ma puli płatnych dni/,
    );
    expect(
      poolSummary({
        form: "uop",
        ring: null,
        entitlement: {
          year: 2026,
          entitlement_days: "26.0",
          carried_over_days: "2.0",
          used_initial_days: "4.5",
        },
        year: 2026,
      }),
    ).toBe("Pula na rok 26 dni · zaległe 2 · przed NEXUSEM 4,5");
    expect(poolSummary({ form: "b2b", ring: null, entitlement: undefined, year: 2026 })).toBe(
      "Pula na 2026 nie jest ustawiona.",
    );
  });
});

describe("raporty godzin w kartotece", () => {
  it("brak raportu to „missing”, godziny wobec normy", () => {
    expect(timesheetStatus(month({ status: null, timesheet_id: null }))).toBe("missing");
    expect(timesheetStatus(month())).toBe("approved");
    expect(hoursOfNorm(month())).toBe("167,5 / 176 h");
  });
});

describe("„← Ludzie” wraca do katalogu z filtrami", () => {
  const origin = "https://nexus.example.com";

  it("poprzedni wpis = katalog → ten adres z filtrami", () => {
    expect(previousPeopleList(`${origin}/people?q=ola&form=b2b`, origin)).toBe(
      "/people?q=ola&form=b2b",
    );
    expect(previousPeopleList(`${origin}/people/`, origin)).toBe("/people");
  });

  it("inny ekran, inna domena albo brak wpisu → `null` (link na `/people`)", () => {
    expect(previousPeopleList(`${origin}/people/approvals`, origin)).toBeNull();
    expect(previousPeopleList(`${origin}/people/12`, origin)).toBeNull();
    expect(previousPeopleList("https://evil.example.org/people", origin)).toBeNull();
    expect(previousPeopleList(null, origin)).toBeNull();
    expect(previousPeopleList("http://[bad", origin)).toBeNull();
  });
});
