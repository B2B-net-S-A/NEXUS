/**
 * Słowa wierszy „Do Twojej decyzji” (22.10.2026): neutralne wobec PIP,
 * premia bez kwoty (D2), wiek sprawy „czeka N dni”.
 */
import { describe, expect, it } from "vitest";

import type { MyTeam, TeamPerson } from "@/lib/api/hr-team";

import { decisionRows, waitingLabel } from "../decision-rows";

function person(extra: Partial<TeamPerson>): TeamPerson {
  return {
    user_id: 1,
    name: "Ola Przykładowa",
    job_title: null,
    employment_type: "b2b",
    employment_status: "active",
    last_working_day: null,
    today: { absent: false },
    covering_for: [],
    week: null,
    leave: null,
    month: null,
    timesheet_required: true,
    bonuses: null,
    to_decide: { leave_requests: [], timesheets: [] },
    ...extra,
  };
}

const TEAM: MyTeam = {
  manager: { user_id: 99, name: "Marta Fikcyjna" },
  is_own: true,
  today: "2026-10-22",
  modules: { leave: true, time: true, payroll: true },
  sees_bonuses: true,
  month: { year: 2026, month: 10, norm_hours: 184, deadline: "2026-11-05" },
  week: null,
  people: [
    person({
      user_id: 2,
      name: "Julia Próbna",
      employment_type: "uop",
      to_decide: {
        leave_requests: [
          {
            id: "lv-1",
            start_date: "2026-11-02",
            end_date: "2026-11-02",
            half_day: "morning",
            leave_type_label: "Urlop wypoczynkowy",
            days_total: "0.5",
            created_at: "2026-10-22T08:00:00+02:00",
          },
        ],
        timesheets: [
          { id: 7, year: 2026, month: 9, link: "/x", submitted_at: "2026-10-21T08:00:00+02:00" },
        ],
      },
    }),
    person({
      user_id: 3,
      name: "Adam Wzorcowy",
      bonuses: {
        count: 2,
        proposals: 2,
        totals: [{ currency: "PLN", amount: "3000.00" }],
        items: [
          { id: 1, amount: "1000.00", currency: "PLN", category_label: "R", status: "proposed", period_year: 2026, period_month: 10, eligible_on: null, description: null },
          { id: 2, amount: "2000.00", currency: "PLN", category_label: "R", status: "proposed", period_year: 2026, period_month: 10, eligible_on: null, description: null },
        ],
      },
    }),
  ],
  stats: { people: 2, absent_today: 0, leave_requests: 1, timesheets: 1, bonus_proposals: 2 },
};

describe("decisionRows", () => {
  it("wniosek, raport godzin i premia — znaczniki i podsumowania", () => {
    const rows = decisionRows(TEAM);
    expect(rows.map((row) => [row.tag, row.name, row.summary, row.age])).toEqual([
      ["nieobecność", "Julia Próbna", "02.11.2026 · 0,5 dnia", "czeka od dziś"],
      // Wrzesień poza bieżącym miesiącem: bez godzin, sam miesiąc.
      ["raport godzin", "Julia Próbna", "wrzesień 2026", "czeka 1 dzień"],
      [
        "do wiadomości",
        "Adam Wzorcowy",
        "wynagrodzenie dodatkowe · 2 propozycje — decydują Płace",
        undefined,
      ],
    ]);
  });

  it("wiersz premii nigdy nie niesie kwoty (D2)", () => {
    const bonus = decisionRows(TEAM).find((row) => row.card.kind === "bonus");
    expect(bonus?.summary).not.toMatch(/\d[\s ]?000|zł|PLN/);
  });

  it("bez `sees_bonuses` nie ma wiersza premii", () => {
    expect(
      decisionRows({ ...TEAM, sees_bonuses: false }).some((row) => row.card.kind === "bonus"),
    ).toBe(false);
  });

  it("słowa neutralne: bez „urlopu”, „premii” i „timesheetu” w znaczniku", () => {
    for (const row of decisionRows(TEAM)) {
      expect(row.tag).not.toMatch(/urlop|premi|timesheet/i);
    }
  });
});

describe("waitingLabel", () => {
  it("od dziś, 1 dzień, N dni; brak daty = brak napisu", () => {
    expect(waitingLabel("2026-10-22T07:00:00+02:00", "2026-10-22")).toBe("czeka od dziś");
    expect(waitingLabel("2026-10-21T07:00:00+02:00", "2026-10-22")).toBe("czeka 1 dzień");
    expect(waitingLabel("2026-10-17T07:00:00+02:00", "2026-10-22")).toBe("czeka 5 dni");
    expect(waitingLabel(null, "2026-10-22")).toBeUndefined();
  });
});
