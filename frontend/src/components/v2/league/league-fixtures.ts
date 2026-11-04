/**
 * Fikcyjne odpowiedzi `/api/competitions/my-league` — dla harnessu
 * `/preview/kpi-topbar` i testów modelu. Osoby i liczby są zmyślone
 * (kwartał z makiety 13.10.2026: dwa tygodnie Q4, wagi 150 / 15 / 5).
 */

import type { LeagueRow, LeagueStanding, MyLeague } from "@/lib/insights-races-api";

const PRIZES = { "1": 5000, "2": 3000, "3": 2000 };

export const LEAGUE_FIXTURE_ME = 104;

function row(userId: number, name: string, value: number, rank: number | null, tied = false): LeagueRow {
  const prize = rank !== null && rank <= 3 ? (tied ? 0 : PRIZES[String(rank) as "1" | "2" | "3"]) : null;
  return { rank, user_id: userId, name, metric_value: value, prize_pln: prize, tied };
}

const LEAGUE_ROWS: LeagueRow[] = [
  row(101, "Marta Wiśniewska", 640, 1),
  row(102, "Kamil Sadowski", 515, 2),
  row(103, "Anna Kowalczyk", 470, 3),
  row(LEAGUE_FIXTURE_ME, "Przykładowa Osoba", 385, 4),
  row(105, "Ola Pietrzak", 340, 5),
  row(106, "Bartek Nowicki", 290, 6),
  row(107, "Zosia Lis", 210, null),
];

function standingFor(rows: LeagueRow[], userId: number, extra: Partial<LeagueStanding> = {}): LeagueStanding {
  const index = rows.findIndex((r) => r.user_id === userId);
  const me = index >= 0 ? rows[index] : null;
  return {
    me: me ? { ...me, qualified: me.rank !== null, placements: 2, interviews: 4, recommendations: 5 } : null,
    rank: me?.rank ?? null,
    value: me?.metric_value ?? 0,
    position_by_value: me ? 1 + rows.filter((r) => r.metric_value > me.metric_value).length : null,
    gap_to_place_above: null,
    lead_over_next: null,
    gap_to_podium: null,
    neighbours: index >= 0 ? rows.slice(Math.max(0, index - 2), index + 3) : [],
    ...extra,
  };
}

function recruiterBase(standing: LeagueStanding): MyLeague {
  return {
    kind: "recruiter",
    type: "quarterly_champions_recruiter",
    period: "Q4 2026",
    days_remaining: 80,
    prizes_pln: PRIZES,
    total: 14,
    standing,
    points_formula: { placement: 150, interview: 15, recommendation: 5 },
    required_placements: 1,
    required_placements_by_month: [1, 2, 3],
  };
}

/** Rekruter na 4. miejscu: 2 placementy, 4 rozmowy, 5 CV = 385 pkt. */
export const LEAGUE_RECRUITER_FOURTH: MyLeague = recruiterBase(
  standingFor(LEAGUE_ROWS, LEAGUE_FIXTURE_ME, { gap_to_place_above: 85, lead_over_next: 45, gap_to_podium: 85 }),
);

export const LEAGUE_RECRUITER_LEADER: MyLeague = recruiterBase({
  ...standingFor(LEAGUE_ROWS, 101, { lead_over_next: 125 }),
  me: { ...LEAGUE_ROWS[0], qualified: true, placements: 3, interviews: 10, recommendations: 8 },
});

export const LEAGUE_RECRUITER_SECOND: MyLeague = recruiterBase({
  ...standingFor(LEAGUE_ROWS, 102, { gap_to_place_above: 125, lead_over_next: 45 }),
  me: { ...LEAGUE_ROWS[1], qualified: true, placements: 3, interviews: 3, recommendations: 4 },
});

const TIED_ROWS: LeagueRow[] = [
  row(101, "Marta Wiśniewska", 640, 1),
  row(102, "Kamil Sadowski", 515, 2),
  row(103, "Anna Kowalczyk", 470, 3, true),
  row(LEAGUE_FIXTURE_ME, "Przykładowa Osoba", 470, 4, true),
  row(105, "Ola Pietrzak", 340, 5),
];

export const LEAGUE_RECRUITER_TIED: MyLeague = recruiterBase({
  ...standingFor(TIED_ROWS, 103, { gap_to_place_above: 45, lead_over_next: 0, tie_for: 3 }),
  me: { ...TIED_ROWS[2], qualified: true, placements: 2, interviews: 9, recommendations: 7 },
});

export const LEAGUE_RECRUITER_UNQUALIFIED: MyLeague = recruiterBase({
  ...standingFor(LEAGUE_ROWS, 107, { gap_to_podium: 260 }),
  me: { ...LEAGUE_ROWS[6], qualified: false, placements: 0, interviews: 11, recommendations: 9 },
  position_by_value: 7,
});

export const LEAGUE_RECRUITER_ZERO: MyLeague = recruiterBase(
  standingFor(LEAGUE_ROWS, 999, { gap_to_podium: 470 }),
);

// Liga DL od 25.10.2026: kolejność po hit ratio, bez nagród, `metric_value` = placementy.
function dlRow(userId: number, name: string, placements: number, hitRatio: number | null, rank: number | null): LeagueRow {
  return { rank, user_id: userId, name, metric_value: placements, hit_ratio: hitRatio, prize_pln: rank ? 0 : null, tied: false };
}

const DL_ROWS: LeagueRow[] = [
  dlRow(201, "Piotr Zając", 5, 41.7, 1),
  dlRow(202, "Ewa Michalska", 4, 36.4, 2),
  dlRow(203, "Tomasz Wrona", 3, 30, 3),
  dlRow(204, "Jola Kruk", 2, 25, null),
];

function dlStanding(userId: number, extra: Partial<LeagueStanding> = {}): LeagueStanding {
  const index = DL_ROWS.findIndex((r) => r.user_id === userId);
  const me = index >= 0 ? DL_ROWS[index] : null;
  return {
    me: me ? { ...me, qualified: me.rank !== null } : null,
    rank: me?.rank ?? null,
    value: me?.hit_ratio ?? 0,
    position_by_value: me ? 1 + DL_ROWS.filter((r) => (r.hit_ratio ?? 0) > (me.hit_ratio ?? 0)).length : null,
    gap_to_place_above: null,
    lead_over_next: null,
    gap_to_podium: null,
    neighbours: index >= 0 ? DL_ROWS.slice(Math.max(0, index - 2), index + 3) : [],
    ...extra,
  };
}

function dlBase(standing: LeagueStanding, dl: MyLeague["dl"]): MyLeague {
  return {
    kind: "delivery_lead",
    type: "quarterly_champions_dl",
    period: "Q4 2026",
    days_remaining: 80,
    prizes_pln: {},
    total: DL_ROWS.length,
    standing,
    dl,
  };
}

const DL_RULES = { hit_ratio_target: 30, min_placements: 3, min_closed_requests: 5 };

export const LEAGUE_DL_SECOND: MyLeague = dlBase(dlStanding(202, { gap_to_place_above: 5.3, lead_over_next: 6.4 }), {
  ...DL_RULES,
  placements: 4,
  closed_requests: 11,
  hit_ratio: 36.4,
  missing_placements: 0,
  missing_closed_requests: 0,
  qualified: true,
});

/** Na liście, ale bez miejsca: 2 placementy z 8 zamkniętych. */
export const LEAGUE_DL_UNPLACED: MyLeague = dlBase(dlStanding(204, { gap_to_podium: 5 }), {
  ...DL_RULES,
  placements: 2,
  closed_requests: 8,
  hit_ratio: 25,
  missing_placements: 1,
  missing_closed_requests: 0,
  qualified: false,
});

export const LEAGUE_DL_NO_CLOSED: MyLeague = dlBase(dlStanding(999), {
  ...DL_RULES,
  placements: 0,
  closed_requests: 0,
  hit_ratio: null,
  missing_placements: 3,
  missing_closed_requests: 5,
  qualified: false,
});

export const LEAGUE_SPECTATOR: MyLeague = {
  kind: "spectator",
  type: "quarterly_champions_recruiter",
  period: "Q4 2026",
  days_remaining: 80,
  prizes_pln: PRIZES,
  total: 14,
  leaders: LEAGUE_ROWS.slice(0, 5),
};
