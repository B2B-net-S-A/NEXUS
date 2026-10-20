import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MyKpiWidget, goalLabel } from "@/components/v2/kpi/MyKpiWidget";
import { TOPBAR_ACTIONS_CLASS, TOPBAR_SEARCH_CLASS } from "@/components/v2/shell/topbar-layout";
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
  short_title_pl: "Weryfikacje",
  description_pl: "Liczy się pierwsze przejście kandydata na „Zweryfikowany”.",
  target: 4,
  current: 1,
  progress_pct: 25,
  state: "behind",
  deadline_hours_left: 4.25,
  expected_count: 2,
};

/** Delivery Lead: 4 rekrutacje zamknięte w kwartale → cel 2 placementy (30% w górę). */
function dlGoals(hitRatio: number | null): MyKpiGoals {
  const counted = hitRatio !== null;
  return {
    kind: "delivery_lead",
    scope_label: "Q3 2026",
    people: null,
    closed_requests: counted ? 4 : 0,
    goals: [
      {
        goal_id: "dl_hit_ratio_quarter",
        title_pl: "Hit ratio portfela w kwartale",
        short_title_pl: "Hit ratio",
        period: "quarter",
        unit: "pct",
        target: 30,
        current: hitRatio,
        progress_pct: hitRatio === null ? null : (hitRatio / 30) * 100,
        state: hitRatio === null ? null : hitRatio >= 30 ? "hit" : "behind",
        note: hitRatio === null ? "Niepoliczony — w tym kwartale nie zamknięto żadnej rekrutacji w Twoim portfelu." : null,
      },
      {
        goal_id: "dl_placements_quarter",
        title_pl: "Placementy portfela w kwartale",
        short_title_pl: "Placementy",
        period: "quarter",
        unit: "count",
        target: counted ? 2 : 0,
        current: 1,
        progress_pct: counted ? 50 : null,
        state: counted ? "behind" : null,
        note: counted
          ? "Rekrutacje zamknięte w kwartale: 4"
          : "Cel pojawi się po zamknięciu pierwszej rekrutacji w kwartale.",
      },
    ],
  };
}

beforeEach(() => {
  state.kpis = [RECRUITER_KPI];
  state.goals = null;
});

// 13.10.2026: do tego dnia pasek pokazywał „↓ 1/4” bez nazwy, a szczegóły
// w dymku na najechanie (role="tooltip").
describe("MyKpiWidget (compact) — podpisane segmenty i panel po kliknięciu", () => {
  it("segment ma nazwę celu, wynik, cel i okres", () => {
    render(<MyKpiWidget />);
    const button = screen.getByRole("button", {
      name: "Twoje cele: Weryfikacje 1 z 4 dziś, poniżej tempa",
    });
    expect(button).toHaveTextContent("Weryfikacje");
    expect(button).toHaveTextContent("/ 4 dziś");
    expect(button).toHaveAttribute("aria-haspopup", "dialog");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/[🎯↓→×]/u)).toBeNull();
  });

  it("ciasny pasek: licznik chowa całe segmenty, zamiast zgniatać wyszukiwarkę", () => {
    // jsdom nie liczy układu, więc przypinamy mechanizm (zmierzony na harnessie
    // 13.10.2026: bez niego przy 1280 px wyszukiwarce zostawało 109 px).
    render(<MyKpiWidget />);
    const button = screen.getByRole("button", { name: /^Twoje cele/ });
    // Zawijanie w przycisku o wysokości jednego wiersza: nadmiarowy segment
    // spada do ukrytego wiersza.
    expect(button).toHaveClass("flex-wrap", "content-start", "overflow-hidden", "h-9");
    // Segment nie łamie tekstu: najmniejsza szerokość przycisku to cały segment
    // (z zawijaniem „/ 180 tydz.” łamało się i wystawało z ukrytego wiersza).
    for (const segment of button.querySelectorAll("[data-kpi-segment]")) {
      expect(segment).toHaveClass("whitespace-nowrap", "overflow-hidden");
    }
    // Wyszukiwarka ma gwarantowane minimum, a grupa akcji kurczy się pierwsza…
    expect(TOPBAR_SEARCH_CLASS.split(" ")).toEqual(
      expect.arrayContaining(["lg:min-w-[140px]", "xl:min-w-[220px]"]),
    );
    expect(TOPBAR_ACTIONS_CLASS.split(" ")).toContain("lg:shrink-[1000]");
    // …ale w grupie ściska się tylko licznik: sąsiedni przycisk-ikona bez
    // `shrink-0` kurczył się z 36 do 22 px.
    expect(TOPBAR_ACTIONS_CLASS.split(" ")).toContain(
      "lg:[&>*:not([data-topbar-shrinks])]:shrink-0",
    );
    expect(button.parentElement).toHaveAttribute("data-topbar-shrinks");
  });

  it("samo najechanie i sam fokus nie otwierają panelu", async () => {
    const user = userEvent.setup();
    render(<MyKpiWidget />);
    const button = screen.getByRole("button", { name: /^Twoje cele/ });

    await user.hover(button);
    await user.tab();
    expect(button).toHaveFocus();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("klik otwiera panel z grupą okresu, stanem i „co się liczy”; Escape zamyka i oddaje fokus", async () => {
    const user = userEvent.setup();
    render(<MyKpiWidget />);
    const button = screen.getByRole("button", { name: /^Twoje cele/ });

    await user.click(button);
    const panel = await screen.findByRole("dialog", { name: "Twoje cele" });
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(within(panel).getByRole("heading", { name: "Dziś" })).toBeInTheDocument();
    expect(within(panel).getByText("do końca dnia pracy: 4 h 15 min")).toBeInTheDocument();
    expect(within(panel).getByText("Poniżej tempa (na tę godzinę: 2).")).toBeInTheDocument();
    expect(
      within(panel).getByText(/Liczy się pierwsze przejście kandydata na „Zweryfikowany”\./),
    ).toBeInTheDocument();
    // Kreska tempa w połowie paska: 2 z 4 na tę godzinę.
    expect(within(panel).getByTestId("kpi-pace-tick")).toHaveStyle({ left: "50%" });
    expect(within(panel).getByRole("link", { name: "Mój miesiąc →" })).toHaveAttribute(
      "href",
      "/insights?tab=moj-miesiac",
    );

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(button).toHaveFocus();
  });

  it("Enter otwiera panel z klawiatury", async () => {
    const user = userEvent.setup();
    render(<MyKpiWidget />);
    await user.tab();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("dialog", { name: "Twoje cele" })).toBeInTheDocument();
  });

  it("Delivery Lead: zamknięte rekrutacje, placementy do celu z 30% i hit ratio", async () => {
    const user = userEvent.setup();
    state.kpis = [];
    state.goals = dlGoals(25);
    render(<MyKpiWidget />);
    const button = screen.getByRole("button", {
      name: "Cel portfela: Placementy 1 z 2, poniżej tempa; Hit ratio 25% z 30%; Zamknięte rekrutacje 4 w Q3",
    });

    await user.click(button);
    const panel = await screen.findByRole("dialog", { name: "Cel portfela" });
    expect(within(panel).getByText("Brakuje 1 placementu.")).toBeInTheDocument();
    expect(within(panel).getByText(/Cel to 30% z 4 zamkniętych rekrutacji\./)).toBeInTheDocument();
    // Pasek hit ratio: skala 0–100% z kreską na progu 30%.
    expect(within(panel).getByTestId("kpi-pace-tick")).toHaveStyle({ left: "30%" });
  });

  it("Delivery Lead bez zamkniętych rekrutacji: sam wynik i notatka, bez „1/0”", async () => {
    const user = userEvent.setup();
    state.kpis = [];
    state.goals = dlGoals(null);
    render(<MyKpiWidget />);
    const button = screen.getByRole("button", { name: /^Cel portfela/ });
    expect(button).not.toHaveTextContent("/ 0");

    await user.click(button);
    const panel = await screen.findByRole("dialog", { name: "Cel portfela" });
    expect(
      within(panel).getByText("Cel pojawi się po zamknięciu pierwszej rekrutacji w kwartale."),
    ).toBeInTheDocument();
    expect(within(panel).getByText("niepoliczony")).toBeInTheDocument();
    expect(within(panel).queryByRole("progressbar")).toBeNull();
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
    expect(screen.getByText("1/2")).toBeInTheDocument();
  });

  it("hit ratio bez requestów jest „niepoliczony”, a nie zerem", () => {
    state.kpis = [];
    state.goals = dlGoals(null);
    render(<MyKpiWidget variant="dashboard" />);
    expect(screen.getByText("niepoliczony")).toBeInTheDocument();
    expect(screen.queryByText("0%/30%")).toBeNull();
    // Placementy bez celu: sam wynik, nie „1/0”.
    expect(screen.queryByText("1/0")).toBeNull();
  });

  it("kind=none i brak KPI → widget nic nie renderuje", () => {
    state.kpis = [];
    state.goals = { kind: "none", scope_label: "", people: null, goals: [] };
    const { container } = render(<MyKpiWidget variant="dashboard" />);
    expect(container).toBeEmptyDOMElement();
    const compact = render(<MyKpiWidget />);
    expect(compact.container).toBeEmptyDOMElement();
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
    // Ułamek z przecinkiem — do 13.10.2026 „62.5%/75%”.
    expect(goalLabel({ ...base, unit: "pct", current: 62.5, target: 75 })).toBe("62,5%/75%");
    expect(goalLabel({ ...base, current: null })).toBe("niepoliczony");
    expect(goalLabel({ ...base, current: 2, target: 0, state: null })).toBe("2");
  });
});
