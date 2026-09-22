import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MyKpiWidget, goalLabel } from "@/components/v2/kpi/MyKpiWidget";
import type { KpiGoal, KpiResult, MyKpiGoals } from "@/lib/api";

const state = vi.hoisted(() => ({
  kpis: [] as KpiResult[],
  goals: null as MyKpiGoals | null,
}));

vi.mock("@/hooks/useMyKpis", () => ({
  useMyKpis: () => ({ isLoading: false, error: null, data: state.kpis }),
}));

vi.mock("@/hooks/useMyGoals", () => ({
  useMyGoals: () => ({ isLoading: false, error: null, data: state.goals }),
}));

const RECRUITER_KPI: KpiResult = {
  kpi_id: "daily_first_verifications",
  period: "day",
  title_pl: "Weryfikacje dziś",
  description_pl: "Kandydaci zweryfikowani",
  target: 4,
  current: 1,
  progress_pct: 25,
  state: "behind",
  deadline_hours_left: 5,
};

function dlGoals(hitRatio: number | null): MyKpiGoals {
  return {
    kind: "delivery_lead",
    scope_label: "Q3 2026",
    people: null,
    goals: [
      {
        goal_id: "dl_hit_ratio_quarter",
        title_pl: "Hit ratio portfela w kwartale",
        period: "quarter",
        unit: "pct",
        target: 30,
        current: hitRatio,
        progress_pct: hitRatio === null ? null : (hitRatio / 30) * 100,
        state: hitRatio === null ? null : hitRatio >= 30 ? "hit" : "behind",
        note: hitRatio === null ? "Niepoliczony — w tym kwartale nie ma nowych requestów w Twoim portfelu." : null,
      },
      {
        goal_id: "dl_placements_quarter",
        title_pl: "Placementy portfela w kwartale",
        period: "quarter",
        unit: "count",
        target: 3,
        current: 1,
        progress_pct: 33.3,
        state: "behind",
        note: "Nowe requesty w kwartale: 4",
      },
    ],
  };
}

beforeEach(() => {
  state.kpis = [RECRUITER_KPI];
  state.goals = null;
});

// Szczegóły KPI były dostępne wyłącznie po najechaniu myszą.
describe("MyKpiWidget (compact) — szczegóły bez myszy", () => {
  it("otwiera szczegóły fokusem klawiatury i zamyka Escape", async () => {
    const user = userEvent.setup();
    render(<MyKpiWidget />);
    expect(screen.queryByRole("tooltip")).toBeNull();

    await user.tab();
    expect(screen.getByRole("button", { name: "Moje KPI" })).toHaveFocus();
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("kliknięcie (dotyk) otwiera szczegóły i nie zamyka ich od razu", async () => {
    const user = userEvent.setup();
    render(<MyKpiWidget />);
    await user.click(screen.getByRole("button", { name: "Moje KPI" }));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
  });
});

// Cele liderów (22.09.2026): DL bez osobistych KPI widział pusty widget.
describe("MyKpiWidget — cele liderów", () => {
  it("Delivery Lead bez osobistych KPI widzi cele portfela", () => {
    state.kpis = [];
    state.goals = dlGoals(25);
    render(<MyKpiWidget variant="dashboard" />);
    expect(screen.getByText("Cele portfela · Q3 2026")).toBeInTheDocument();
    expect(screen.getByText("Hit ratio portfela w kwartale")).toBeInTheDocument();
    expect(screen.getByText("25%/30%")).toBeInTheDocument();
    expect(screen.getByText("1/3")).toBeInTheDocument();
  });

  it("hit ratio bez requestów jest „niepoliczony”, a nie zerem", () => {
    state.kpis = [];
    state.goals = dlGoals(null);
    render(<MyKpiWidget variant="dashboard" />);
    expect(screen.getByText("niepoliczony")).toBeInTheDocument();
    expect(screen.queryByText("0%/30%")).toBeNull();
  });

  it("kind=none i brak KPI → widget nic nie renderuje", () => {
    state.kpis = [];
    state.goals = { kind: "none", scope_label: "", people: null, goals: [] };
    const { container } = render(<MyKpiWidget variant="dashboard" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("formatuje etykiety celów", () => {
    const base: KpiGoal = {
      goal_id: "x",
      title_pl: "x",
      period: "day",
      unit: "count",
      target: 20,
      current: 7,
      progress_pct: 35,
      state: "behind",
      note: null,
    };
    expect(goalLabel(base)).toBe("7/20");
    expect(goalLabel({ ...base, unit: "pct", current: 62.5, target: 75 })).toBe("62.5%/75%");
    expect(goalLabel({ ...base, current: null })).toBe("niepoliczony");
  });
});
