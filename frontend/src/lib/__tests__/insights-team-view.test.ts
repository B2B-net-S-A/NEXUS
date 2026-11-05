import { describe, expect, it } from "vitest";

import type { InFlightResponse, RecruitmentFunnelResponse, TeamGoalsResponse } from "@/lib/insights-api";
import type { TeamPeopleRow } from "@/lib/insights-team-api";
import {
  groupedPeople,
  isFairComparison,
  periodName,
  stageNotRecorded,
  monthlySeries,
  niceAxisMax,
  peopleWithGoal,
  personGroup,
  rankedSignals,
  teamVerdict,
  tempoRows,
  weeklySeries,
} from "@/lib/insights-team-view";

const OCTOBER = { kind: "month", start: "2026-10-01T00:00:00+02:00", end: "2026-11-01T00:00:00+01:00", timezone: "Europe/Warsaw" } as RecruitmentFunnelResponse["period"];
const NOVEMBER = { ...OCTOBER, start: "2026-11-01T00:00:00+01:00", end: "2026-12-01T00:00:00+01:00" };

function funnel(period: RecruitmentFunnelResponse["period"], counts: Record<string, number>): RecruitmentFunnelResponse {
  return { period, stages: Object.entries(counts).map(([stage, count]) => ({ stage, count })) } as unknown as RecruitmentFunnelResponse;
}

function row(extra: Partial<TeamPeopleRow>): TeamPeopleRow {
  return { user_id: 1, name: "Anna Test", role: "recruiter", is_active: true, verifications: 0, recommendations: 0, interviews: 0, acceptances: 0, placements: 0, placements_target: 1, previous_placements: 0, verifications_per_workday: 0, precision_pct: null, ...extra };
}

const GOALS = {
  company_month_placements: 1,
  goals: [
    { goal_id: "team_daily_first_verifications", target: 72, current: 10, expected: 30 },
    { goal_id: "team_weekly_cvs_sent", target: 270, current: 75, expected: 180 },
    { goal_id: "team_monthly_placements", target: 36, current: 1, expected: 6 },
    { goal_id: "team_monthly_precision", target: 75, current: 77, expected: null },
  ],
} as unknown as TeamGoalsResponse;

const IN_FLIGHT = {
  stale_days: 10,
  columns: [
    { column: "cv_qc", label: "", count: 48, stale_count: 16, oldest_days: 51 },
    { column: "cv_sent", label: "", count: 675, stale_count: 453, oldest_days: 174 },
  ],
  acceptances: [{ days: 20 }, { days: 3 }],
  forecast: { open: 7, hired: 18, resolved: 20, min_sample: 10, since: "2026-10-12", rate_pct: 90, low: 6, high: 7 },
} as unknown as InFlightResponse;

describe("teamVerdict", () => {
  it("okres, który trwa: plan na dziś i szacunek z akceptacji wobec celu", () => {
    const { pace, stall } = teamVerdict({ window: NOVEMBER, running: true, workdays: 4, funnel: funnel(NOVEMBER, { hired: 1 }), goals: GOALS, inFlight: IN_FLIGHT, rows: [] });
    expect(pace).toBe("Listopad 2026, 4. dzień roboczy: 1 placement przy planie 6 na dziś. W akceptacjach ok. 6–7 kolejnych, razem ok. 7–8 z celu 36.");
    expect(stall).toBe("Dziś najwięcej stoi u klientów: 453 z 675 par dłużej niż 10 dni.");
  });

  it("okres zamknięty: licznik firmy i osób z celem stoją obok siebie, gdy się różnią", () => {
    const rows = [row({ placements: 19, placements_target: 36 })];
    const { pace } = teamVerdict({ window: OCTOBER, running: false, workdays: 22, funnel: funnel(OCTOBER, { hired: 26 }), goals: GOALS, inFlight: IN_FLIGHT, rows });
    expect(pace).toBe("Październik 2026: 26 placementów w firmie, 19 u osób z celem 36. Do celu zabrakło 17.");
  });

  it("okres, który trwa: licznik firmy inny niż osób z celem stoi obok planu", () => {
    const goals = { ...GOALS, goals: GOALS.goals.map((g) => (g.goal_id === "team_monthly_placements" ? { ...g, current: 3 } : g)) } as TeamGoalsResponse;
    const { pace } = teamVerdict({ window: NOVEMBER, running: true, workdays: 4, funnel: funnel(NOVEMBER, { hired: 12 }), goals, inFlight: undefined, rows: [] });
    expect(pace).toBe("Listopad 2026, 4. dzień roboczy: 12 placementów w firmie, 3 u osób z celem przy planie 6 na dziś. Cel miesiąca: 36.");
  });

  it("miesiąc sprzed 2026 nie dostaje dzisiejszych celów", () => {
    const january = { ...OCTOBER, start: "2025-01-01T00:00:00+01:00", end: "2025-02-01T00:00:00+01:00" };
    const rows = [row({ placements: 1, placements_target: 3 })];
    const { pace } = teamVerdict({ window: january, running: false, workdays: 21, funnel: funnel(january, { hired: 5 }), goals: GOALS, inFlight: undefined, rows });
    expect(pace).toBe("Styczeń 2025: 5 placementów.");
  });

  it("cel osiągnięty i te same liczby: jedno zdanie bez rozbicia", () => {
    const rows = [row({ placements: 5, placements_target: 3 })];
    const { pace } = teamVerdict({ window: OCTOBER, running: false, workdays: 22, funnel: funnel(OCTOBER, { hired: 5 }), goals: GOALS, inFlight: undefined, rows });
    expect(pace).toBe("Październik 2026: 5 placementów przy celu 3. Cel osiągnięty.");
  });

  it("bez wglądu w osoby okres zamknięty nie zmyśla celu", () => {
    const { pace } = teamVerdict({ window: OCTOBER, running: false, workdays: null, funnel: funnel(OCTOBER, { hired: 26 }), goals: GOALS, inFlight: undefined, rows: [] });
    expect(pace).toBe("Październik 2026: 26 placementów.");
  });

  it("nic nie stoi ponad próg: bez drugiego zdania", () => {
    const inFlight = { ...IN_FLIGHT, columns: [{ column: "cv_sent", label: "", count: 5, stale_count: 0, oldest_days: 2 }] } as InFlightResponse;
    expect(teamVerdict({ window: NOVEMBER, running: true, workdays: 4, funnel: funnel(NOVEMBER, { hired: 1 }), goals: GOALS, inFlight, rows: [] }).stall).toBeNull();
  });
});

describe("tempoRows", () => {
  it("okres, który trwa: horyzonty celów i kreska planu", () => {
    const rows = tempoRows({ window: NOVEMBER, running: true, workdays: 4, funnel: funnel(NOVEMBER, { hired: 1 }), goals: GOALS, inFlight: IN_FLIGHT, rows: [] });
    expect(rows.map((r) => r.horizon)).toEqual(["dziś", "ten tydzień", "ten miesiąc", "30 dni"]);
    expect(rows[2]).toMatchObject({ current: 1, target: 36, expected: 6, forecast: 8 });
  });

  it("okres zamknięty: cel dnia i tygodnia razy dni robocze, bez kreski planu", () => {
    const people = [row({ placements: 19, placements_target: 36 })];
    const rows = tempoRows({ window: OCTOBER, running: false, workdays: 22, funnel: funnel(OCTOBER, { verified: 730, cv_sent: 647, hired: 26 }), goals: GOALS, inFlight: IN_FLIGHT, rows: people });
    expect(rows[0]).toMatchObject({ current: 730, target: 1584, expected: null });
    expect(rows[1]).toMatchObject({ current: 647, target: 1188 });
    expect(rows[2]).toMatchObject({ current: 19, target: 36, note: "w firmie 26" });
  });
});

describe("tempoRows poza miesiącem", () => {
  const YEAR = { ...OCTOBER, kind: "year", start: "2025-01-01T00:00:00+01:00", end: "2026-01-01T00:00:00+01:00" } as RecruitmentFunnelResponse["period"];

  it("rok nie dostaje celu z dzisiejszych wartości razy dni, a nie policzono to nie 0", () => {
    const stages = funnel(YEAR, { verified: 0, cv_sent: 0, hired: 40 });
    stages.stages = stages.stages.map((s) => (s.stage === "verified" ? { ...s, counted_from: "2026-01-01" } : s));
    const rows = tempoRows({ window: YEAR, running: false, workdays: 250, funnel: stages, goals: GOALS, inFlight: undefined, rows: [] });
    expect(rows[0]).toMatchObject({ current: null, target: null });
    expect(rows[1]).toMatchObject({ current: 0, target: null });
    expect(rows[2]).toMatchObject({ current: 40, target: null });
  });

  it("precyzja bez wartości nie udaje 0%", () => {
    const goals = { ...GOALS, goals: GOALS.goals.map((g) => (g.goal_id === "team_monthly_precision" ? { ...g, current: null } : g)) } as unknown as TeamGoalsResponse;
    const rows = tempoRows({ window: NOVEMBER, running: true, workdays: 4, funnel: funnel(NOVEMBER, { hired: 1 }), goals, inFlight: undefined, rows: [] });
    expect(rows[3]).toMatchObject({ current: null, target: 75 });
  });
});

describe("periodName i etap bez danych", () => {
  it("nazwa niesie rok i rodzaj okresu", () => {
    expect(periodName(OCTOBER)).toBe("Październik 2026");
    expect(periodName({ ...OCTOBER, kind: "quarter", start: "2026-07-01T00:00:00+02:00", end: "2026-10-01T00:00:00+02:00" })).toBe("III kwartał 2026");
    expect(periodName({ ...OCTOBER, kind: "year", start: "2025-01-01T00:00:00+01:00", end: "2026-01-01T00:00:00+01:00" })).toBe("Rok 2025");
    expect(periodName({ ...OCTOBER, kind: "custom", start: "2025-11-05T00:00:00+01:00", end: "2026-11-06T00:00:00+01:00" })).toBe("5.11.2025 – 5.11.2026");
  });

  it("okno przed dniem, od którego etap się liczy, to brak danych; okno przecinające ten dzień ma liczbę", () => {
    const september = { ...OCTOBER, start: "2026-09-01T00:00:00+02:00", end: "2026-10-01T00:00:00+02:00" };
    const before = funnel(september, { acceptance: 0 });
    before.stages = before.stages.map((s) => ({ ...s, counted_from: "2026-10-12" }));
    expect(stageNotRecorded(before, "acceptance")).toBe(true);
    const crossing = funnel(OCTOBER, { acceptance: 27 });
    crossing.stages = crossing.stages.map((s) => ({ ...s, counted_from: "2026-10-12" }));
    expect(stageNotRecorded(crossing, "acceptance")).toBe(false);
  });
});

describe("peopleWithGoal", () => {
  it("nie liczy byłych członków zespołu ani osób z celem 0", () => {
    const rows = [row({ placements: 2, placements_target: 3 }), row({ placements: 4, placements_target: 1, is_active: false }), row({ placements: 1, placements_target: 0 })];
    expect(peopleWithGoal(rows)).toEqual({ target: 3, placements: 2 });
    expect(peopleWithGoal([])).toBeNull();
  });
});

describe("rankedSignals", () => {
  it("układa od najbliższych placementu i dokłada akceptacje oraz nazwiska", () => {
    const signals = rankedSignals(
      [
        { kind: "stale_postings", count: 28, label: "zgłoszeń", report: null },
        { kind: "low_precision", count: 1, label: "osób", report: null, user_ids: [7] },
        { kind: "dl_send_stale", count: 26, label: "CV", report: null, href: "/jobs?tosend=stale" },
      ],
      IN_FLIGHT,
      [row({ user_id: 7, name: "Ewa Test" })],
      true,
    );
    expect(signals.map((s) => s.kind)).toEqual(["stale_acceptances", "dl_send_stale", "low_precision", "stale_postings"]);
    expect(signals[0].count).toBe(1);
    expect(signals[2].names).toEqual(["Ewa Test"]);
    // Sygnał bez listy nie udaje linku do tabeli, w której go nie ma.
    expect(signals[3].href).toBeNull();
  });

  it("bez sekcji Pipeline adres listy rekrutacji znika, raport zostaje", () => {
    const signals = rankedSignals(
      [
        { kind: "dl_send_stale", count: 26, label: "CV", report: null, href: "/jobs?tosend=stale" },
        { kind: "stale_jobs", count: 5, label: "bez ruchu", report: "bez-ruchu", href: "/jobs?stale=1" },
      ],
      undefined,
      [],
      false,
    );
    expect(signals.map((s) => s.href)).toEqual([null, "/insights?tab=raporty&report=bez-ruchu"]);
  });
});

describe("personGroup", () => {
  it("grupa to najdalszy etap w okresie, a cel 0 idzie do osobnej grupy", () => {
    expect(personGroup(row({ placements: 1 }))).toBe("placed");
    expect(personGroup(row({ acceptances: 1 }))).toBe("near");
    expect(personGroup(row({ interviews: 2 }))).toBe("near");
    expect(personGroup(row({ recommendations: 3 }))).toBe("sending");
    expect(personGroup(row({ verifications: 3 }))).toBe("quiet");
    expect(personGroup(row({ placements: 4, placements_target: 0 }))).toBe("no_goal");
  });

  it("poza oknem miesiąca celu nie ma: decyduje rola", () => {
    expect(personGroup(row({ placements_target: null, recommendations: 1 }))).toBe("sending");
    expect(personGroup(row({ placements_target: null, role: "delivery_lead", recommendations: 1 }))).toBe("no_goal");
  });

  it("w grupie wyżej stoi ten, kto dalej doszedł", () => {
    const groups = groupedPeople([row({ user_id: 1, placements: 1, recommendations: 9 }), row({ user_id: 2, placements: 3 })]);
    expect(groups[0].rows.map((r) => r.user_id)).toEqual([2, 1]);
  });
});

describe("serie w czasie", () => {
  const counts = (verified: number | null, cv: number | null, interview: number | null, acceptance: number | null, hired: number | null) => ({ verified, cv_sent: cv, client_interview: interview, acceptance, hired });

  it("trwający tydzień nie idzie na linię, a mianownik 0 to brak wartości", () => {
    const series = weeklySeries([
      { week_start: "2026-10-05", partial: false, counts: counts(100, 80, 0, null, 2) },
      { week_start: "2026-10-12", partial: false, counts: counts(100, 80, 20, 5, 10) },
      { week_start: "2026-10-19", partial: true, counts: counts(1, 1, 1, 1, 1) },
    ]);
    expect(series.labels).toEqual(["5.10", "12.10"]);
    expect(series.cutoverIndex).toBe(1);
    expect(series.conversions.verified_cv[0]).toEqual({ num: 80, den: 100, value: 80 });
    expect(series.conversions.interview_acceptance[0].value).toBeNull();
    expect(series.conversions.acceptance_hired[0].value).toBeNull();
    // Bez sufitu: więcej placementów niż akceptacji to informacja, nie błąd.
    expect(series.conversions.acceptance_hired[1].value).toBe(200);
  });

  it("miesiąc przecinający 12.10: przejścia z akceptacjami tylko z dni od tej daty", () => {
    const series = monthlySeries([
      { month_start: "2026-09-01", partial: false, counts: counts(700, 470, 110, null, 38), cutover_counts: null },
      { month_start: "2026-10-01", partial: false, counts: counts(730, 647, 114, 27, 26), cutover_counts: counts(519, 460, 94, 27, 21) },
      { month_start: "2026-11-01", partial: true, counts: counts(1, 1, 1, 1, 1), cutover_counts: null },
    ]);
    expect(series.labels).toEqual(["wrz", "paź"]);
    expect(series.cutoverIndex).toBe(1);
    expect(series.conversions.interview_acceptance[1]).toEqual({ num: 27, den: 94, value: 29 });
    expect(series.conversions.acceptance_hired[1]).toEqual({ num: 21, den: 27, value: 78 });
    expect(series.conversions.verified_cv[1]).toEqual({ num: 647, den: 730, value: 89 });
  });
});

describe("drobne reguły", () => {
  it("niceAxisMax daje czytelny szczyt osi", () => {
    expect(niceAxisMax(3)).toBe(4);
    expect(niceAxisMax(12)).toBe(20);
    expect(niceAxisMax(271)).toBe(300);
    expect(niceAxisMax(932)).toBe(1000);
  });

  it("isFairComparison: tylko trwający okres z poprzednikiem sprzed 12.10 jest nieuczciwy", () => {
    expect(isFairComparison(true, "2026-10-01T00:00:00+02:00")).toBe(false);
    expect(isFairComparison(true, "2026-11-01T00:00:00+01:00")).toBe(true);
    expect(isFairComparison(false, "2026-09-01T00:00:00+02:00")).toBe(true);
  });
});
