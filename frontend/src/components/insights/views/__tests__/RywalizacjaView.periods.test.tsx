/**
 * „Rywalizacja” — wybór kwartału Ligi i miesiąca wyścigów (decyzja Artura
 * 15.10.2026: rozliczona historia od stycznia 2026, okresy do 11.10.2026
 * z DynaReportera).
 *
 * Reguły pod ochroną:
 *
 * 1. **Domyślnie trwający okres, zapytanie jak dotąd** — bez `period`, więc
 *    cache serwera i zasiewy harnessu dla bieżącego okresu zostają te same.
 * 2. **Obie ligi idą za jednym kwartałem**, a wyścigi za swoim miesiącem.
 * 3. **Lista zaczyna się w styczniu 2026** i liczy kalendarz warszawski, nie
 *    strefę przeglądarki.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));
// Kampania i remisy mają własne testy; tu tylko wybór okresu.
vi.mock("@/components/insights/sections/CompetitionTiesAdmin", () => ({
  CompetitionTiesAdmin: () => null,
}));

import { RywalizacjaView } from "../RywalizacjaView";
import {
  currentQuarterKey,
  isClosedQuarter,
  monthPeriodOptions,
  quarterPeriodOptions,
} from "@/lib/insights-races-api";

const LEAGUE = "/api/competitions/current?type=";
const RACES = "/api/competitions/monthly-races";

function league(type: string, period: string) {
  return {
    type,
    period,
    top3: [],
    full_ranking: [],
    is_frozen: false,
    days_remaining: 77,
    requirement: null,
    points_formula: null,
    quarterly_prizes_pln: null,
  };
}

function race(period: string) {
  return {
    period,
    days_remaining: 16,
    prize: { amount_pln: 1500, name: "Nagroda testowa" },
    requirements: [],
    ranking: [],
    excluded_user_ids: [],
    qualified_leader: null,
  };
}

/**
 * Liga po pełnym URL-u (okres w query stringu), wyścigi po ścieżce i `params`.
 * Paski Hall of Fame i ścieżki rozwoju czekają bez końca — nie są tematem.
 */
function respondByPeriod() {
  mocks.get.mockImplementation(
    (url: string, config?: { params?: { period?: string } }) => {
      if (url.startsWith(LEAGUE)) {
        const query = new URLSearchParams(url.split("?")[1]);
        const type = query.get("type") ?? "";
        const period = query.get("period") ?? "Q4 2026";
        return Promise.resolve({ data: league(type, period) });
      }
      if (url === RACES) {
        const races = race(config?.params?.period ?? "2026-10");
        return Promise.resolve({
          data: { recommendations: races, placements: races },
        });
      }
      return new Promise(() => {});
    },
  );
}

function renderView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RywalizacjaView />
    </QueryClientProvider>,
  );
}

function urls(): string[] {
  return mocks.get.mock.calls.map((call) => call[0] as string);
}

beforeEach(() => {
  mocks.get.mockReset();
  // Tylko zegar — timery zostają prawdziwe, żeby React Query i userEvent szły.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-15T10:00:00+02:00"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("RywalizacjaView — wybór okresu", () => {
  it("domyślnie trwający kwartał i miesiąc, zapytania bez `period`", async () => {
    respondByPeriod();
    renderView();

    const quarter = screen.getByLabelText("Kwartał") as HTMLSelectElement;
    const month = screen.getByLabelText("Miesiąc") as HTMLSelectElement;
    expect(quarter.value).toBe("Q4 2026");
    expect(quarter.selectedOptions[0].textContent).toBe("Q4 2026 · trwa");
    expect(month.value).toBe("2026-10");
    expect(month.selectedOptions[0].textContent).toBe("Październik 2026 · trwa");

    await waitFor(() =>
      expect(urls()).toContain(`${LEAGUE}quarterly_champions_recruiter`),
    );
    expect(urls()).toContain(`${LEAGUE}quarterly_champions_dl`);
    expect(mocks.get).toHaveBeenCalledWith(RACES, { params: undefined });
    expect(urls().some((url) => url.includes("period="))).toBe(false);
  });

  it("zmiana kwartału pyta o niego obie ligi", async () => {
    const user = userEvent.setup();
    respondByPeriod();
    renderView();

    await user.selectOptions(screen.getByLabelText("Kwartał"), "Q2 2026");

    await waitFor(() =>
      expect(urls()).toContain(
        `${LEAGUE}quarterly_champions_recruiter&period=Q2%202026`,
      ),
    );
    expect(urls()).toContain(`${LEAGUE}quarterly_champions_dl&period=Q2%202026`);
    // Wyścigi nie słuchają kwartału.
    expect(mocks.get).not.toHaveBeenCalledWith(RACES, {
      params: { period: expect.any(String) },
    });
    // Miniony kwartał nie odlicza dni dzisiejszego.
    expect(await screen.findAllByText("Zakończony")).toHaveLength(2);
  });

  it("zmiana miesiąca pyta o niego wyścigi, a powrót na trwający — bez `period`", async () => {
    const user = userEvent.setup();
    respondByPeriod();
    renderView();

    const month = screen.getByLabelText("Miesiąc");
    await user.selectOptions(month, "2026-07");
    await waitFor(() =>
      expect(mocks.get).toHaveBeenCalledWith(RACES, {
        params: { period: "2026-07" },
      }),
    );
    // Nagłówki obu kart (`<p>`), nie opcja listy o tym samym tekście.
    expect(
      await screen.findAllByText("Lipiec 2026", { selector: "p" }),
    ).toHaveLength(2);

    await user.selectOptions(month, "2026-10");
    expect((month as HTMLSelectElement).value).toBe("2026-10");
    // Trwający miesiąc wraca z cache tego samego klucza — żadnego
    // zapytania z `period=2026-10`.
    expect(mocks.get).not.toHaveBeenCalledWith(RACES, {
      params: { period: "2026-10" },
    });
  });
});

describe("listy okresów", () => {
  const now = new Date("2026-10-15T10:00:00+02:00");

  it("kwartały od trwającego do Q1 2026, najnowszy pierwszy", () => {
    expect(quarterPeriodOptions(now).map((o) => o.label)).toEqual([
      "Q4 2026 · trwa",
      "Q3 2026",
      "Q2 2026",
      "Q1 2026",
    ]);
    expect(quarterPeriodOptions(now).filter((o) => o.current)).toHaveLength(1);
  });

  it("miesiące od trwającego do stycznia 2026", () => {
    const options = monthPeriodOptions(now);
    expect(options).toHaveLength(10);
    expect(options[0]).toEqual({
      value: "2026-10",
      label: "Październik 2026 · trwa",
      current: true,
    });
    expect(options[options.length - 1].value).toBe("2026-01");
  });

  it("w 2027 lista sięga dalej wstecz do stycznia 2026", () => {
    const next = new Date("2027-02-10T10:00:00+01:00");
    expect(quarterPeriodOptions(next).map((o) => o.value)).toEqual([
      "Q1 2027",
      "Q4 2026",
      "Q3 2026",
      "Q2 2026",
      "Q1 2026",
    ]);
    expect(monthPeriodOptions(next)).toHaveLength(14);
  });

  it("granica kwartału liczy się w Warszawie, nie w UTC", () => {
    // 30.09 22:30 UTC = 1.10 00:30 w Warszawie — już Q4.
    const midnight = new Date("2026-09-30T22:30:00Z");
    expect(currentQuarterKey(midnight)).toBe("Q4 2026");
    expect(isClosedQuarter("Q3 2026", midnight)).toBe(true);
    expect(isClosedQuarter("Q4 2026", midnight)).toBe(false);
    // Nierozpoznany zapis = nie wiemy, więc nie „zakończony”.
    expect(isClosedQuarter("2026-Q3", midnight)).toBe(false);
  });
});
