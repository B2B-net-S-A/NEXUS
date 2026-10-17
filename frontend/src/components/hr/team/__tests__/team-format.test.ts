import { describe, expect, it } from "vitest";

import type { MyTeam, TeamPerson } from "@/lib/api/hr-team";

import {
  bonusCell,
  decisionItems,
  leaveCell,
  monthCell,
  todayCell,
} from "../team-format";

function person(extra: Partial<TeamPerson> = {}): TeamPerson {
  return {
    user_id: 1,
    name: "Ola Przykładowa",
    job_title: "Rekruterka",
    employment_type: "b2b",
    employment_status: "active",
    last_working_day: null,
    today: { absent: false },
    covering_for: [],
    leave: { has_pool: false, remaining_days: null, planned_days: "0.0", pending_days: "0.0" },
    month: { hours: 121, status: "draft", timesheet_id: 5 },
    timesheet_required: true,
    bonuses: null,
    to_decide: { leave_requests: [], timesheets: [] },
    ...extra,
  };
}

const team = {
  month: { year: 2091, month: 10, norm_hours: 176, deadline: "2091-11-05" },
} as MyTeam;

describe("„Mój zespół” — komórki", () => {
  it("dziś: w pracy (z zastępstwem) albo rodzaj do kiedy", () => {
    expect(todayCell({ absent: false }, ["Dawid Demo"])).toEqual({
      text: "w pracy",
      sub: "zastępuje: Dawid Demo",
    });
    const away = todayCell(
      { absent: true, until: "2091-10-23", leave_type_label: "Urlop wypoczynkowy", substitute_name: "Kamil Testowy" },
      [],
    );
    expect(away.text).toBe("Urlop wypoczynkowy do wt 23.10");
    expect(away.sub).toBe("zastępca: Kamil Testowy");
    expect(todayCell(null, [])).toEqual({ text: "—", tone: "muted" });
  });

  it("nieobecności: pula tylko u osób z pulą, reszta — zaplanowane dni", () => {
    expect(
      leaveCell({ has_pool: true, remaining_days: "11.5", planned_days: "3.0", pending_days: "0.0" }),
    ).toEqual({ text: "zostało 11,5 dnia urlopu", sub: "zaplanowane 3 dni" });
    expect(
      leaveCell({ has_pool: false, remaining_days: null, planned_days: "2.0", pending_days: "1.0" }),
    ).toEqual({ text: "zaplanowane 2 dni", sub: "czeka 1 dzień" });
    expect(
      leaveCell({ has_pool: false, remaining_days: null, planned_days: "0.0", pending_days: "0.0" }).text,
    ).toBe("nic zaplanowanego");
    expect(leaveCell(null).text).toBe("—");
  });

  it("miesiąc: godziny do normy i status timesheetu", () => {
    expect(monthCell(person(), team)).toEqual({ text: "121/176 h", sub: "do wysłania" });
    expect(monthCell(person({ month: null, timesheet_required: false }), team).text).toBe(
      "bez timesheetu",
    );
    expect(monthCell(person(), { ...team, month: null }).text).toBe("—");
  });

  it("premie: liczba i suma, propozycje do wiadomości; brak prawa to „—”, nie zero", () => {
    const cell = bonusCell({
      count: 2,
      proposals: 1,
      totals: [{ currency: "PLN", amount: "3000.00" }],
      items: [],
    });
    expect(cell.text).toMatch(/^2 · 3\s?000\szł$/);
    expect(cell.sub).toBe("1 propozycja — decydują Płace");
    expect(bonusCell(null).text).toBe("—");
    expect(bonusCell({ count: 0, proposals: 0, totals: [], items: [] }).text).toBe("—");
  });

  it("do decyzji: wnioski i timesheety z linkami", () => {
    const items = decisionItems(
      person({
        to_decide: {
          leave_requests: [
            { id: "a", start_date: "2091-12-23", end_date: "2091-12-31", half_day: null, leave_type_label: "Urlop", days_total: "5.0" },
          ],
          timesheets: [{ id: 7, year: 2091, month: 10, link: "/people/approvals?kind=timesheet" }],
        },
      }),
    );
    expect(items.map((item) => item.text)).toEqual([
      "wniosek 23–31.12.2091",
      "timesheet: październik 2091",
    ]);
    expect(items[1].href).toBe("/people/approvals?kind=timesheet");
  });
});
