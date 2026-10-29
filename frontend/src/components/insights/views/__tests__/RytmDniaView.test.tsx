/**
 * Insights → „Rytm dnia” (28.10.2026): urlop zamiast godzin, wyniki
 * i podpowiedź tylko gdy serwer je przysłał (liderzy), awaria nie udaje
 * pustki, progi reguł muszą rosnąć. 29.10.2026: ochrona przed nabijaniem
 * i rozkład dnia po kliknięciu (co się liczyło, a co odpadło i dlaczego).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), params: new URLSearchParams() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args), put: vi.fn() },
  api: { get: (...args: unknown[]) => mocks.get(...args), put: vi.fn() },
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => mocks.params,
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/insights",
}));

import { RytmDniaView } from "@/components/insights/views/RytmDniaView";
import { DayBreakdown } from "@/components/insights/views/RhythmDayDialog";
import { draftProblem } from "@/components/insights/views/RhythmRulesDialog";
import type { WorkRhythmDay, WorkRhythmDayDetail, WorkRhythmResponse, WorkRhythmRules } from "@/lib/work-rhythm-api";

const RULES: WorkRhythmRules = {
  weights: { screening: 5, client_step: 3, cv: 3, note: 2, contact: 1, action: 1, view: 0.5 },
  hour_levels: [4, 11, 25],
  work_hour_min_points: 4,
  min_work_hours: 7,
  norm_day_points: 120,
  level_high: 75,
  level_mid: 50,
  diag_intensity: 60,
  diag_results_pct: 80,
  auto_cv_points: 0,
  screening_per_candidate_day: 1,
  repeats_per_hour: 1,
  views_per_hour: 4,
  bulk_per_minute: 10,
  stage_return_points: 0,
  contacts_per_day: 10,
  thin_hour_candidates: 2,
  break_minutes: 30,
};

function day(date: string, over: Partial<WorkRhythmDay> = {}): WorkRhythmDay {
  return {
    date,
    before_start: false,
    in_progress: false,
    leave: 0,
    points: Array(13).fill(5),
    levels: Array(13).fill(2),
    counts: Array(13).fill(3),
    meetings: Array(13).fill(false),
    thin: Array(13).fill(false),
    skipped: {},
    first: "09:00",
    last: "17:00",
    work_hours: 8,
    work_time: 8.5,
    day_points: 65,
    index: 80,
    ...over,
  };
}

function body(over: Partial<WorkRhythmResponse> = {}): WorkRhythmResponse {
  return {
    from: "2026-10-26",
    to: "2026-10-27",
    days: ["2026-10-26", "2026-10-27"],
    rules: RULES,
    people: [
      {
        user_id: 1,
        name: "Anna Testowa",
        days: [day("2026-10-26"), day("2026-10-27")],
        index: 80,
        level: "high",
        worked_days: 2,
        leave_days: 0,
        days_before_start: 0,
        avg_work_hours: 8,
        avg_work_time: 8.5,
        full_days: 2,
        timed_days: 2,
        median_points: 65,
      },
      {
        user_id: 2,
        name: "Bartek Przykładowy",
        days: [
          day("2026-10-26"),
          day("2026-10-27", { leave: 1, index: null, work_hours: null, first: null, last: null }),
        ],
        index: 70,
        level: "mid",
        worked_days: 1,
        leave_days: 1,
        days_before_start: 0,
        avg_work_hours: 6,
        avg_work_time: 6,
        full_days: 0,
        timed_days: 1,
        median_points: 50,
      },
    ],
    team_cv_per_day_median: null,
    can_edit_rules: false,
    with_results: false,
    ...over,
  };
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RytmDniaView />
    </QueryClientProvider>,
  );
}

describe("RytmDniaView", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.params = new URLSearchParams();
  });

  it("dzień urlopu ma pasek zamiast godzin i nie liczy się do wskaźnika", async () => {
    mocks.get.mockResolvedValue({ data: body() });
    renderView();
    expect(await screen.findByText("Urlop — dzień nie liczy się do wskaźnika")).toBeInTheDocument();
    expect(screen.getByText("Anna Testowa")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/insights/work-rhythm", { params: {} });
  });

  it("bez wyników z serwera nie rysuje kolumn wyników ani edycji reguł", async () => {
    mocks.params = new URLSearchParams("widok=intensywnosc");
    mocks.get.mockResolvedValue({ data: body() });
    renderView();
    expect(await screen.findByText("Bez wyników w tym widoku.")).toBeInTheDocument();
    expect(screen.queryByText("Podpowiedź dla lidera")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zmień reguły/ })).not.toBeInTheDocument();
  });

  it("HoR i admin widzą CV do klienta, podpowiedź i edycję reguł, gdy serwer je przysłał", async () => {
    mocks.params = new URLSearchParams("widok=intensywnosc");
    const data = body({ with_results: true, can_edit_rules: true, team_cv_per_day_median: 2 });
    data.people[0] = { ...data.people[0], cv_sent: 1, cv_per_day: 0.5, results_pct: 25, diagnosis: "quality" };
    data.people[1] = { ...data.people[1], cv_sent: 4, cv_per_day: 4, results_pct: 200, diagnosis: "short_good" };
    mocks.get.mockResolvedValue({ data });
    renderView();
    expect(await screen.findByText("Podpowiedź dla lidera")).toBeInTheDocument();
    expect(screen.getAllByText("Pomóż z jakością").length).toBeGreaterThan(0);
    // Poniżej 8 h dobre wyniki nie robią wzoru (decyzja Artura 29.10.2026).
    expect(screen.getAllByText("Dobre wyniki, poniżej 8 h").length).toBeGreaterThan(0);
    expect(screen.getByText("6 h 00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Zmień reguły/ })).toBeInTheDocument();
  });

  it("kliknięcie osoby otwiera rozkład dnia z serwera", async () => {
    const detail: WorkRhythmDayDetail = {
      user_id: 1,
      name: "Anna Testowa",
      date: "2026-10-27",
      points: Array(13).fill(0),
      meetings: Array(13).fill(false),
      thin: Array(13).fill(false),
      skipped: {},
      work_time: 0,
      spans: [],
      events: [],
    };
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({ data: url.endsWith("/day") ? detail : body() }),
    );
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: /Anna Testowa/ }));
    expect(await screen.findByText("Tego dnia nie ma żadnej akcji w NEXUSIE.")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/insights/work-rhythm/day", { params: { user_id: 1, day: "2026-10-27" } });
  });

  it("awaria nie wygląda jak pusta lista", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("boom"), { response: { status: 500 } }));
    renderView();
    expect(await screen.findByText(/Rytm dnia/)).toBeInTheDocument();
    expect(screen.queryByText("Brak aktywnych rekruterów w tym okresie.")).not.toBeInTheDocument();
  });
});

describe("draftProblem", () => {
  it("odrzuca progi, które nie rosną, i średnią ≥ wysokiej", () => {
    expect(draftProblem(RULES)).toBeNull();
    expect(draftProblem({ ...RULES, hour_levels: [11, 4, 25] })).toMatch(/muszą rosnąć/);
    expect(draftProblem({ ...RULES, level_mid: 80 })).toMatch(/niższy niż/);
    expect(draftProblem({ ...RULES, norm_day_points: Number.NaN })).toMatch(/liczby/);
  });
});

describe("DayBreakdown", () => {
  it("pokazuje, co się liczyło, a co odpadło i dlaczego", () => {
    const points = Array(13).fill(0);
    points[3] = 2.5;
    const thin = Array(13).fill(false);
    thin[3] = true;
    render(
      <DayBreakdown
        data={{
          user_id: 1,
          name: "Anna Testowa",
          date: "2026-10-27",
          points,
          meetings: Array(13).fill(false),
          thin,
          skipped: { limit_podgladow: 1.5 },
          work_time: 1.25,
          spans: [["09:00", "09:50"], ["10:05", "10:30"]],
          events: [
            { time: "10:05", hour: 10, kind: "view", label: "Podgląd dokumentu", candidate: "Jan Próbny", points: 0.5, weight: 0.5, reason: null },
            { time: "10:06", hour: 10, kind: "view", label: "Podgląd dokumentu", candidate: null, points: 0, weight: 0.5, reason: "limit_podgladow" },
            { time: "10:20", hour: 10, kind: "action", label: "Ruch karty → Screening", candidate: null, points: 2, weight: 1, reason: null },
          ],
        }}
      />,
    );
    expect(screen.getByText(/1,5 pkt: ponad limit podglądów w godzinie/)).toBeInTheDocument();
    expect(screen.getAllByText("2,5 pkt").length).toBe(2);
    expect(screen.getByText("0 — ponad limit podglądów w godzinie")).toBeInTheDocument();
    expect(screen.getByText(/nie jest godziną pracy/)).toBeInTheDocument();
    expect(screen.getByText(/Jan Próbny/)).toBeInTheDocument();
    expect(screen.getByText("1 h 15")).toBeInTheDocument();
    expect(screen.getByText(/Przerwy: 09:50–10:05 \(15 min\)/)).toBeInTheDocument();
  });
});

describe("draftProblem — ochrona", () => {
  it("odrzuca ujemne limity, 0 = bez limitu przechodzi", () => {
    expect(draftProblem({ ...RULES, views_per_hour: 0 })).toBeNull();
    expect(draftProblem({ ...RULES, contacts_per_day: -1 })).toMatch(/ujemne/);
  });
});

describe("draftProblem — przerwa", () => {
  it("przerwa musi mieć 10–180 minut", () => {
    expect(draftProblem({ ...RULES, break_minutes: 5 })).toMatch(/Przerwa/);
  });
});
