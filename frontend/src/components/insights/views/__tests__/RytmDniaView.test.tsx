/**
 * Insights → „Rytm dnia” (28.10.2026): urlop zamiast godzin, wyniki
 * i podpowiedź tylko gdy serwer je przysłał (liderzy), awaria nie udaje
 * pustki, progi reguł muszą rosnąć.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
import { draftProblem } from "@/components/insights/views/RhythmRulesDialog";
import type { WorkRhythmDay, WorkRhythmResponse, WorkRhythmRules } from "@/lib/work-rhythm-api";

const RULES: WorkRhythmRules = {
  weights: { screening: 5, client_step: 3, cv: 3, note: 2, action: 1, view: 0.5 },
  hour_levels: [4, 11, 25],
  work_hour_min_points: 4,
  norm_work_hours: 7,
  norm_day_points: 120,
  level_high: 75,
  level_mid: 50,
  diag_intensity: 60,
  diag_results_pct: 80,
};

function day(date: string, over: Partial<WorkRhythmDay> = {}): WorkRhythmDay {
  return {
    date,
    before_start: false,
    leave: 0,
    points: Array(13).fill(5),
    levels: Array(13).fill(2),
    counts: Array(13).fill(3),
    meetings: Array(13).fill(false),
    first: "09:00",
    last: "17:00",
    work_hours: 8,
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
    mocks.get.mockResolvedValue({ data });
    renderView();
    expect(await screen.findByText("Podpowiedź dla lidera")).toBeInTheDocument();
    expect(screen.getAllByText("Pomóż z jakością").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Zmień reguły/ })).toBeInTheDocument();
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
