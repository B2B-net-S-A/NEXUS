/**
 * Pasek filtrów listy rekrutacji (02.10.2026): kolejność przycisków, nowe
 * filtry „Priorytet” i „Data otwarcia” oraz układ liczony od SZEROKOŚCI PASKA
 * — nie okna (przypięte menu, szyna otwartych kart i dok zabierają mu miejsce
 * niezależnie od ekranu). jsdom nie liczy układu, więc szerokość podajemy
 * przez `getBoundingClientRect`, a zmianę — przez `ResizeObserver`.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  JOBS_FILTER_BAR_FULL_MIN_WIDTH,
  JOBS_FILTER_BAR_OPENED_PILL_MIN_WIDTH,
  JobsFilterBar,
  jobsFilterBarLayout,
  type JobsFilterBarValue,
} from "@/components/v2/jobs/JobsFilterBar";

vi.mock("@/lib/api", () => ({
  default: { get: () => Promise.resolve({ data: [] }) },
}));

vi.mock("@/components/v2/filters/UserMultiSelect", () => ({
  UserMultiSelect: () => null,
}));
vi.mock("@/components/v2/filters/ClientMultiSelect", () => ({
  ClientMultiSelect: () => null,
}));
vi.mock("@/components/v2/filters/CompetenceCategoryMultiSelect", () => ({
  CompetenceCategoryMultiSelect: () => null,
}));

const EMPTY: JobsFilterBarValue = {
  clientIds: [],
  deliveryLeadIds: [],
  workedBy: [],
  nobodyWorking: false,
  ccIds: [],
  deadline: "any",
  deadlineRange: {},
  sent: "any",
  priorityLevels: [],
  openedRange: {},
};

let barWidth = 0;
let resizeCallbacks: Array<() => void> = [];

beforeEach(() => {
  barWidth = 0;
  resizeCallbacks = [];
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
    this: HTMLElement,
  ) {
    const width = this.getAttribute("data-help") === "jobs.list.filters" ? barWidth : 0;
    return { width, height: 0, top: 0, left: 0, right: width, bottom: 0, x: 0, y: 0, toJSON: () => ({}) };
  });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resizeCallbacks.push(callback);
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function renderBar(
  value: Partial<JobsFilterBarValue> = {},
  props: Partial<React.ComponentProps<typeof JobsFilterBar>> = {},
) {
  const onPatch = vi.fn();
  const view = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <JobsFilterBar
        value={{ ...EMPTY, ...value }}
        onPatch={onPatch}
        meId={7}
        activeCount={0}
        canClear={false}
        onClearAll={vi.fn()}
        {...props}
      />
    </QueryClientProvider>,
  );
  const bar = screen.getByRole("group", { name: "Filtry listy rekrutacji" });
  return { ...view, onPatch, bar };
}

/** Nazwy dostępne przycisków paska, w kolejności ekranu (bez „Wyczyść: …”). */
function pillNames(bar: HTMLElement): string[] {
  return within(bar)
    .getAllByRole("button")
    .map((button) => button.getAttribute("aria-label") ?? button.textContent ?? "")
    .filter((name) => !name.startsWith("Wyczyść"));
}

describe("jobsFilterBarLayout — progi szerokości paska", () => {
  it("bez pomiaru i poniżej progu „Data otwarcia” mieszka w „Więcej filtrów”", () => {
    expect(jobsFilterBarLayout(null)).toBe("narrow");
    // Okno 1280 px: ~920 px paska przy przypiętym menu, ~1100 px przy zwiniętym.
    expect(jobsFilterBarLayout(920)).toBe("narrow");
    expect(jobsFilterBarLayout(1108)).toBe("narrow");
    expect(jobsFilterBarLayout(JOBS_FILTER_BAR_OPENED_PILL_MIN_WIDTH - 1)).toBe("narrow");
  });

  it("od progu własny przycisk, a pełne etykiety dopiero na szerokim pasku", () => {
    expect(jobsFilterBarLayout(JOBS_FILTER_BAR_OPENED_PILL_MIN_WIDTH)).toBe("medium");
    expect(jobsFilterBarLayout(JOBS_FILTER_BAR_FULL_MIN_WIDTH - 1)).toBe("medium");
    expect(jobsFilterBarLayout(JOBS_FILTER_BAR_FULL_MIN_WIDTH)).toBe("wide");
    expect(jobsFilterBarLayout(2248)).toBe("wide");
  });
});

describe("JobsFilterBar — kolejność i nazwy", () => {
  it("przyciski: Delivery Lead · Klient · Rekruter · Kategoria · Priorytet · Termin · Więcej filtrów, potem trzy przełączniki", () => {
    const { bar } = renderBar();
    expect(bar).toHaveAttribute("data-layout", "narrow");
    expect(pillNames(bar)).toEqual([
      "Delivery LeadDL",
      "Klient",
      "Rekruter",
      "Kategoria",
      "Priorytet",
      "Termin",
      "Więcej filtrówWięcej",
      "Po terminie",
      "Bez rekrutera",
      "Nikogo nie wysłano",
    ]);
    // Stare nazwy zniknęły.
    expect(within(bar).queryByText(/Kto pracuje|Nikt nie pracuje/)).not.toBeInTheDocument();
  });

  it("szeroki pasek: „Data otwarcia” ma własny przycisk między „Termin” a „Więcej filtrów”", () => {
    barWidth = 1700;
    const { bar } = renderBar();
    expect(bar).toHaveAttribute("data-layout", "wide");
    const names = pillNames(bar);
    expect(names.slice(5, 8)).toEqual(["Termin", "Data otwarcia", "Więcej filtrówWięcej"]);
    // Pełne etykiety: krótka forma „DL” jest schowana, a „Wyczyść filtry” w całości.
    expect(within(bar).getByText("DL")).toHaveClass("hidden");
    expect(within(bar).getByText("Delivery Lead")).not.toHaveClass("sr-only");
  });

  it("średni pasek: własny przycisk „Data otwarcia”, ale nadal krótkie etykiety", () => {
    barWidth = 1300;
    const { bar } = renderBar();
    expect(bar).toHaveAttribute("data-layout", "medium");
    expect(pillNames(bar)).toContain("Data otwarcia");
    expect(within(bar).getByText("Delivery Lead")).toHaveClass("sr-only");
    expect(within(bar).getByText("DL")).not.toHaveClass("hidden");
  });

  it("układ idzie za szerokością paska, gdy ta się zmienia (menu, szyna, dok)", () => {
    barWidth = 1300;
    const { bar } = renderBar();
    expect(pillNames(bar)).toContain("Data otwarcia");

    barWidth = 930;
    act(() => resizeCallbacks.forEach((callback) => callback()));
    expect(bar).toHaveAttribute("data-layout", "narrow");
    expect(pillNames(bar)).not.toContain("Data otwarcia");
  });
});

describe("JobsFilterBar — „Data otwarcia” w „Więcej filtrów” (wąski pasek)", () => {
  it("pola daty są w okienku „Więcej filtrów”, a przycisk liczy schowany filtr", async () => {
    const user = userEvent.setup();
    const { bar, onPatch } = renderBar({ openedRange: { from: "2026-09-01", to: "2026-09-30" } });

    const more = within(bar).getByRole("button", { name: /Więcej filtrów: otwarta: 01\.09–30\.09/ });
    await user.click(more);
    expect(await screen.findByLabelText("Data otwarcia od")).toHaveValue("2026-09-01");
    expect(screen.getByLabelText("Data otwarcia do")).toHaveValue("2026-09-30");

    // „✕” przy „Więcej filtrów” czyści także schowany filtr.
    await user.click(within(bar).getByRole("button", { name: "Wyczyść: Więcej filtrów" }));
    expect(onPatch).toHaveBeenCalledWith({ sent: "any", openedRange: {} });
  });

  it("dwa schowane filtry naraz: licznik zamiast jednej wartości", () => {
    const { bar } = renderBar({ sent: "3", openedRange: { from: "2026-09-01" } });
    const more = within(bar).getByRole("button", { name: /^Więcej filtrów/ });
    expect(more).toHaveTextContent("2");
    expect(more).not.toHaveTextContent("otwarta");
  });

  it("szeroki pasek: „Więcej filtrów” nie liczy daty otwarcia i jej nie czyści", async () => {
    barWidth = 1300;
    const user = userEvent.setup();
    const { bar, onPatch } = renderBar({ sent: "3", openedRange: { from: "2026-09-01" } });

    expect(
      within(bar).getByRole("button", { name: /Więcej filtrów: wysłanych: co najmniej 3 osoby/ }),
    ).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: /^Data otwarcia: od 01\.09$/ })).toBeInTheDocument();

    await user.click(within(bar).getByRole("button", { name: "Wyczyść: Więcej filtrów" }));
    expect(onPatch).toHaveBeenCalledWith({ sent: "any" });
    await user.click(within(bar).getByRole("button", { name: "Wyczyść: Data otwarcia" }));
    expect(onPatch).toHaveBeenCalledWith({ openedRange: {} });

    await user.click(within(bar).getByRole("button", { name: /^Więcej filtrów/ }));
    expect(await screen.findByRole("combobox", { name: "Filtr: Wysłanych do klienta" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Data otwarcia od")).not.toBeInTheDocument();
  });

  it("odwrócony zakres: prośba o poprawkę przy polach i na przycisku", async () => {
    barWidth = 1300;
    const user = userEvent.setup();
    const { bar } = renderBar({ openedRange: { from: "2026-09-30", to: "2026-09-01" } });
    await user.click(within(bar).getByRole("button", { name: /^Data otwarcia: popraw zakres$/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Data „od” jest późniejsza niż „do” — popraw zakres, żeby go zastosować.",
    );
    expect(screen.getByLabelText("Data otwarcia od")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("JobsFilterBar — „Priorytet” i „Wyczyść”", () => {
  it("trzy poziomy do zaznaczenia; przycisk niesie krótkie nazwy wybranych", async () => {
    const user = userEvent.setup();
    const { bar, onPatch } = renderBar({ priorityLevels: ["p1"] });
    await user.click(within(bar).getByRole("button", { name: /^Priorytet: P1$/ }));

    const group = within(await screen.findByRole("group", { name: "Priorytet rekrutacji" }));
    expect(group.getAllByRole("checkbox").map((box) => box.parentElement?.textContent)).toEqual([
      "P1 Pilne",
      "P2 Standard",
      "Przyjmujemy kandydatów",
    ]);
    expect(group.getByRole("checkbox", { name: "P1 Pilne" })).toBeChecked();

    await user.click(group.getByRole("checkbox", { name: "Przyjmujemy kandydatów" }));
    expect(onPatch).toHaveBeenLastCalledWith({ priorityLevels: ["p1", "accepting"] });
    await user.click(group.getByRole("checkbox", { name: "P1 Pilne" }));
    expect(onPatch).toHaveBeenLastCalledWith({ priorityLevels: [] });
  });

  it("„Wyczyść filtry (N)” zachowuje pełną nazwę dostępną także na wąskim pasku", () => {
    const { bar } = renderBar({ priorityLevels: ["p1"] }, { canClear: true, activeCount: 1 });
    expect(within(bar).getByRole("button", { name: "Wyczyść filtry (1)" })).toBeInTheDocument();
  });
});
