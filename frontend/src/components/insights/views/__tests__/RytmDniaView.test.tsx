/**
 * Insights → „Rytm dnia” (28.10.2026): urlop zamiast godzin, wyniki
 * i podpowiedź tylko gdy serwer je przysłał (liderzy), awaria nie udaje
 * pustki, progi reguł muszą rosnąć. 29.10.2026: ochrona przed nabijaniem
 * i rozkład dnia po kliknięciu (co się liczyło, a co odpadło i dlaczego).
 * 30.10.2026: bez czasu pracy i minimum 8 h — porównanie z zespołem,
 * przerwy na heatmapie, Wzorce (typowy dzień) i Trend (tydzień do tygodnia).
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
  norm_active_hours: 8,
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
    gaps: [],
    day_points: 65,
    index: 80,
    ...over,
  };
}

const PATTERN = {
  pattern_days: 2,
  profile: null,
  typical_start: null,
  typical_end: null,
  start_spread: null,
  peak_hour: null,
  morning_share: null,
};

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
        median_points: 65,
        ...PATTERN,
        profile: [0, 10, 30, 20, 12, 6, 5, 5, 4, 3, 0, 0, 0],
        typical_start: 8.5,
        typical_end: 17,
        start_spread: 0.4,
        peak_hour: 9,
        morning_share: 72,
        trend_prev: 50,
        trend_last: 80,
        trend: 30,
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
        median_points: 50,
        ...PATTERN,
        pattern_days: 1,
        trend_prev: 72,
        trend_last: 70,
        trend: -2,
      },
    ],
    team_cv_per_day_median: null,
    team_day_index: { "2026-10-26": 70, "2026-10-27": 70 },
    team_profile: [0, 5, 10, 10, 10, 8, 6, 8, 12, 6, 0, 0, 0],
    trend_prev: ["2026-10-19", "2026-10-23"],
    trend_last: ["2026-10-26"],
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

  it("Dzień: bez czasu pracy, z przerwami i różnicą do mediany zespołu", async () => {
    const data = body();
    data.people[0].days[1] = day("2026-10-27", { gaps: [[11, 13]], index: 80 });
    mocks.get.mockResolvedValue({ data });
    renderView();
    expect(await screen.findByText("11–13")).toBeInTheDocument();
    expect(screen.getByText("+10")).toBeInTheDocument();
    expect(screen.getByText(/Intensywność · zespół 70/)).toBeInTheDocument();
    expect(screen.queryByText(/Czas pracy/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Brakuje/)).not.toBeInTheDocument();
  });

  it("Wzorce: typowy dzień, mediana zespołu i osoby bez wzorca", async () => {
    mocks.params = new URLSearchParams("widok=wzorce");
    mocks.get.mockResolvedValue({ data: body() });
    renderView();
    expect(await screen.findByText("Zespół (mediana)")).toBeInTheDocument();
    expect(screen.getByText("poranny")).toBeInTheDocument();
    // Jedna osoba ze wzorcem: jej start to też mediana zespołu.
    expect(screen.getAllByText("8:30")).toHaveLength(2);
    expect(screen.getByText("stała")).toBeInTheDocument();
    expect(screen.getByText(/Za mało pełnych dni na wzorzec \(potrzeba 3\): Bartek Przykładowy \(1\)/)).toBeInTheDocument();
  });

  it("Trend: zmiana tydzień do tygodnia, dawny adres „Intensywność” prowadzi do Trendu", async () => {
    mocks.params = new URLSearchParams("widok=intensywnosc");
    mocks.get.mockResolvedValue({ data: body() });
    renderView();
    expect(await screen.findByText("+30")).toBeInTheDocument();
    expect(screen.getByText("-2")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Trend" })).toHaveAttribute("aria-selected", "true");
  });

  it("bez wyników z serwera nie rysuje kolumn wyników ani edycji reguł", async () => {
    mocks.params = new URLSearchParams("widok=trend");
    mocks.get.mockResolvedValue({ data: body() });
    renderView();
    expect(await screen.findByText("Ostatnio")).toBeInTheDocument();
    expect(screen.queryByText("Podpowiedź dla lidera")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zmień reguły/ })).not.toBeInTheDocument();
  });

  it("HoR i admin widzą CV do klienta, podpowiedź i edycję reguł, gdy serwer je przysłał", async () => {
    mocks.params = new URLSearchParams("widok=trend");
    const data = body({ with_results: true, can_edit_rules: true, team_cv_per_day_median: 2 });
    data.people[0] = { ...data.people[0], cv_sent: 1, cv_per_day: 0.5, results_pct: 25, diagnosis: "quality" };
    data.people[1] = { ...data.people[1], cv_sent: 4, cv_per_day: 4, results_pct: 200, diagnosis: "efficient" };
    mocks.get.mockResolvedValue({ data });
    renderView();
    expect(await screen.findByText("Podpowiedź dla lidera")).toBeInTheDocument();
    expect(screen.getAllByText("Pomóż z jakością").length).toBeGreaterThan(0);
    // Bez godzin (30.10.2026): dobry wynik przy małej liczbie akcji to nie „za mało pracy”.
    expect(screen.getAllByText("Wynik przy niskiej intensywności").length).toBeGreaterThan(0);
    expect(screen.queryByText(/poniżej 8 h/)).not.toBeInTheDocument();
    expect(screen.getByText("Intensywność × wyniki")).toBeInTheDocument();
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
      gaps: [],
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
          gaps: [[11, 13], [14, 15]],
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
    expect(screen.getByText("11:00–13:00, 14:00–15:00")).toBeInTheDocument();
    expect(screen.queryByText(/Czas pracy/)).not.toBeInTheDocument();
  });
});

describe("draftProblem — ochrona", () => {
  it("odrzuca ujemne limity, 0 = bez limitu przechodzi", () => {
    expect(draftProblem({ ...RULES, views_per_hour: 0 })).toBeNull();
    expect(draftProblem({ ...RULES, contacts_per_day: -1 })).toMatch(/ujemne/);
  });
});

describe("draftProblem — norma aktywnych godzin", () => {
  it("norma musi mieć 1–10 h", () => {
    expect(draftProblem({ ...RULES, norm_active_hours: 0 })).toMatch(/Norma aktywnych godzin/);
    expect(draftProblem({ ...RULES, norm_active_hours: 12 })).toMatch(/Norma aktywnych godzin/);
  });
});
