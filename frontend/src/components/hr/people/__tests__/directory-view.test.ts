import { describe, expect, it } from "vitest";

import type { PersonCard, PersonFull } from "@/lib/api/hr";

import {
  NO_DEPARTMENT,
  departmentDot,
  formLabel,
  groupByDepartment,
  isAwayToday,
  tenureLabel,
  todayChips,
} from "../directory-view";

const TODAY = "2026-10-19";

function card(overrides: Partial<PersonCard> = {}): PersonCard {
  return {
    user_id: 1,
    name: "Ola Przykładowa",
    email: "ola@example.com",
    job_title: "Rekruterka",
    department: "Rekrutacja IT",
    phone: null,
    default_location: "onsite",
    employment_status: "active",
    manager_user_id: null,
    manager_name: null,
    scope: "card",
    today: null,
    ...overrides,
  };
}

function full(overrides: Partial<PersonFull> = {}): PersonFull {
  return {
    ...card(),
    scope: "full",
    employment_type: "b2b",
    employment_type_pending: false,
    hired_on: null,
    work_start_date: "2025-03-03",
    last_working_day: null,
    timesheet_required: true,
    can_log_overtime: false,
    roles: ["recruiter"],
    ...overrides,
  };
}

describe("todayChips — kolumna „Dziś”", () => {
  it("bez wpisu i z otwartym modułem urlopów/czasu = „w pracy”", () => {
    expect(todayChips(card(), TODAY, true)).toEqual([{ tone: "success", label: "w pracy" }]);
  });

  it("bez modułów urlopów i czasu nie zgaduje „w pracy”", () => {
    expect(todayChips(card(), TODAY, false)).toEqual([]);
  });

  it("nieobecność widziana z wizytówki nie zdradza formy ani rodzaju", () => {
    const chips = todayChips(
      card({
        today: {
          absent_until: "2026-10-21",
          half_day: null,
          substitute_name: "Marta Fikcyjna",
          presence: null,
        },
      }),
      TODAY,
      true,
    );
    expect(chips).toEqual([
      { tone: "info", label: "nieobecność do śr 21.10 · zastępuje Marta F." },
    ]);
  });

  it("przy widocznej formie mówi słowem formy („przerwa”, „urlop”)", () => {
    const absent = {
      absent_until: "2026-10-21",
      half_day: null,
      substitute_name: null,
      presence: null,
    } as const;
    expect(todayChips(full({ today: absent }), TODAY, true)[0].label).toBe(
      "przerwa do śr 21.10",
    );
    expect(
      todayChips(full({ employment_type: "uop", today: absent }), TODAY, true)[0].label,
    ).toBe("urlop do śr 21.10");
  });

  it("nieobecność tylko dziś i pół dnia", () => {
    const chips = todayChips(
      card({
        today: { absent_until: TODAY, half_day: "morning", substitute_name: null, presence: null },
      }),
      TODAY,
      true,
    );
    expect(chips[0].label).toBe("nieobecność dziś (pół dnia)");
  });

  it("delegacja i praca zdalna z „Mojego miesiąca”", () => {
    const trip = card({
      today: { absent_until: null, half_day: null, substitute_name: null, presence: "business_trip" },
    });
    expect(todayChips(trip, TODAY, true)).toEqual([{ tone: "neutral", label: "delegacja" }]);
    expect(isAwayToday(trip)).toBe(true);
    const remote = card({
      today: { absent_until: null, half_day: null, substitute_name: null, presence: "remote" },
    });
    expect(todayChips(remote, TODAY, true)).toEqual([{ tone: "success", label: "zdalnie" }]);
    expect(isAwayToday(remote)).toBe(false);
  });

  it("odejście w toku: data tylko z pełnej kartoteki", () => {
    expect(
      todayChips(full({ employment_status: "offboarding", last_working_day: "2026-11-30" }), TODAY, true),
    ).toEqual([
      { tone: "success", label: "w pracy" },
      { tone: "warning", label: "odchodzi 30.11" },
    ]);
    expect(todayChips(card({ employment_status: "offboarding" }), TODAY, false)).toEqual([
      { tone: "warning", label: "odchodzi" },
    ]);
  });

  it("start w przyszłości wygrywa z resztą", () => {
    expect(todayChips(full({ work_start_date: "2026-11-04" }), TODAY, true)).toEqual([
      { tone: "neutral", label: "start 04.11" },
    ]);
  });
});

describe("formLabel", () => {
  it("forma tylko z pełnej kartoteki, gdy serwer ją zwrócił", () => {
    expect(formLabel(card())).toBeNull();
    expect(formLabel(full({ employment_type: null }))).toBeNull();
    expect(formLabel(full())).toBe("B2B");
    expect(formLabel(full({ employment_type: "uop" }))).toBe("UoP");
  });

  it("student na zleceniu i forma do uzupełnienia", () => {
    expect(
      formLabel(full({ employment_type: "zlecenie", student_contribution_exempt: true })),
    ).toBe("Zlecenie · student");
    expect(formLabel(full({ employment_type_pending: true }))).toBe("uzupełnij");
  });
});

describe("tenureLabel", () => {
  it("lata i miesiące po polsku", () => {
    expect(tenureLabel("2025-03-03", TODAY)).toBe("1 rok 7 mies.");
    expect(tenureLabel("2024-10-19", TODAY)).toBe("2 lata");
    expect(tenureLabel("2021-10-01", TODAY)).toBe("5 lat");
    expect(tenureLabel("2026-02-20", TODAY)).toBe("7 mies.");
    expect(tenureLabel("2026-10-01", TODAY)).toBe("< 1 mies.");
  });

  it("brak daty albo start w przyszłości = brak stażu", () => {
    expect(tenureLabel(null, TODAY)).toBeNull();
    expect(tenureLabel("2026-11-04", TODAY)).toBeNull();
  });
});

describe("groupByDepartment", () => {
  it("działy alfabetycznie, „Bez działu” na końcu, kolejność osób zostaje", () => {
    const groups = groupByDepartment([
      { name: "B", department: "Delivery" },
      { name: "A", department: null },
      { name: "C", department: "Administracja" },
      { name: "D", department: "Delivery" },
      { name: "E", department: "  " },
    ]);
    expect(groups.map((g) => [g.department, g.rows.map((r) => r.name)])).toEqual([
      ["Administracja", ["C"]],
      ["Delivery", ["B", "D"]],
      [NO_DEPARTMENT, ["A", "E"]],
    ]);
  });

  it("kropka działu z palety tokenów, „Bez działu” wyciszony", () => {
    const names = ["Administracja", "Delivery", NO_DEPARTMENT];
    expect(departmentDot("Administracja", names)).toBe("bg-chart-1");
    expect(departmentDot("Delivery", names)).toBe("bg-chart-2");
    expect(departmentDot(NO_DEPARTMENT, names)).toBe("bg-muted-foreground/40");
  });
});
