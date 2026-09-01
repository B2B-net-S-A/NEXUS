/**
 * Liga Mistrzów na `/insights` — podium 1-2-3 (parytet z DynaReporterem).
 *
 * Reguły pod ochroną, każda raz już zawiodła na produkcji:
 *
 * 1. **Podium ma trzy miejsca** i pokazuje rozbicie „P / I / R" — sam numer
 *    punktów nie mówi, z czego się wziął.
 * 2. **`qualified: false` jest OZNACZONY, nie ukryty.** Backend celowo zostawia
 *    taką osobę w rankingu (`competitions.py`); widok, który ją usuwa, zamienia
 *    „próg niespełniony" w „zero wyniku".
 * 3. **Reguła gry jest na ekranie** — `points_formula` i `requirement`. Ranking
 *    rozdzielający 5000/3000/2000 PLN bez widocznej formuły jest wyrocznią.
 * 4. **Awaria ≠ pustka.** Pusty ranking to spokojny stan; 500 to komunikat
 *    z ponowieniem.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import { ChampionsSection } from "@/components/insights/sections/ChampionsSection";

const RECRUITER =
  "/api/competitions/current?type=quarterly_champions_recruiter";
const DL = "/api/competitions/current?type=quarterly_champions_dl";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

/** Odpowiedzi po DOKŁADNYM URL-u — obie ligi jadą na tej samej ścieżce. */
function respond(map: Record<string, unknown>) {
  mocks.get.mockImplementation((url: string) => {
    if (!(url in map)) {
      return Promise.reject(new Error(`Nieoczekiwany URL w teście: ${url}`));
    }
    const value = map[url];
    if (value instanceof Error) return Promise.reject(value);
    return Promise.resolve({ data: value });
  });
}

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ChampionsSection />
    </QueryClientProvider>,
  );
}

function entry(over: Record<string, unknown> = {}) {
  return {
    user_id: 1,
    name: "Anna Kowalska",
    metric_value: 480,
    hit_ratio: null,
    rank: 1,
    prize_pln: 5000,
    role: "recruiter",
    placements: 9,
    interviews: 25,
    recommendations: 60,
    verifications: 200,
    qualified: true,
    required_placements: 3,
    disqualification_reasons: [],
    ...over,
  };
}

const EMPTY_LEAGUE = {
  type: "quarterly_champions_dl",
  period: "Q3 2026",
  top3: [],
  full_ranking: [],
  is_frozen: false,
  target_pct: 30.0,
  days_remaining: 12,
  prize_pool_pln: 10000,
  requirement: "Wymagane hit ratio ≥ 30% oraz minimum 3 placementy w kwartale.",
  points_formula: null,
  quarterly_prizes_pln: { "1": 5000, "2": 3000, "3": 2000 },
};

const RECRUITER_LEAGUE = {
  type: "quarterly_champions_recruiter",
  period: "Q3 2026",
  top3: [
    entry(),
    entry({
      user_id: 2,
      name: "Bartek Nowak",
      rank: 2,
      metric_value: 310,
      prize_pln: 3000,
      placements: 5,
      interviews: 12,
      recommendations: 40,
    }),
    entry({
      user_id: 3,
      name: "Celina Wójcik",
      rank: 3,
      metric_value: 205,
      prize_pln: 2000,
      placements: 3,
      interviews: 8,
      recommendations: 20,
    }),
  ],
  full_ranking: [
    entry(),
    entry({
      user_id: 2,
      name: "Bartek Nowak",
      metric_value: 310,
      placements: 5,
      interviews: 12,
      recommendations: 40,
    }),
    entry({
      user_id: 3,
      name: "Celina Wójcik",
      metric_value: 205,
      placements: 3,
      interviews: 8,
      recommendations: 20,
    }),
  ],
  is_frozen: false,
  target_pct: null,
  days_remaining: 12,
  prize_pool_pln: 10000,
  requirement:
    "Wymagane minimum 2 placementy w kwartale (próg rośnie z każdym miesiącem kwartału).",
  points_formula: { placement: 150, interview: 15, recommendation: 5 },
  quarterly_prizes_pln: { "1": 5000, "2": 3000, "3": 2000 },
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ChampionsSection — podium", () => {
  it("renderuje trzy miejsca z rozbiciem P / I / R", async () => {
    respond({ [RECRUITER]: RECRUITER_LEAGUE, [DL]: EMPTY_LEAGUE });

    renderSection();

    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
    expect(screen.getByText("Bartek Nowak")).toBeInTheDocument();
    expect(screen.getByText("Celina Wójcik")).toBeInTheDocument();
    // Rozbicie oryginału („9P / 25I / 60R") — bez niego liczba punktów jest
    // nieweryfikowalna z ekranu.
    expect(screen.getByText("9P / 25I / 60R")).toBeInTheDocument();
    expect(screen.getByText("5P / 12I / 40R")).toBeInTheDocument();
    expect(screen.getByText("3P / 8I / 20R")).toBeInTheDocument();
    // Formuła i warunek udziału są na ekranie — inaczej ranking jest wyrocznią.
    expect(screen.getByText(/150 pkt/)).toBeInTheDocument();
    expect(
      screen.getByText(/Wymagane minimum 2 placementy w kwartale/),
    ).toBeInTheDocument();
  });

  it("oznacza niezakwalifikowanego zamiast go ukryć", async () => {
    respond({
      [RECRUITER]: {
        ...RECRUITER_LEAGUE,
        top3: [
          entry({
            user_id: 4,
            name: "Dawid Zieliński",
            rank: 1,
            metric_value: 120,
            placements: 0,
            qualified: false,
            required_placements: 2,
            disqualification_reasons: ["MIN_PLACEMENTS_NOT_MET"],
          }),
        ],
        full_ranking: [
          entry({
            user_id: 4,
            name: "Dawid Zieliński",
            metric_value: 120,
            placements: 0,
            qualified: false,
            required_placements: 2,
            disqualification_reasons: ["MIN_PLACEMENTS_NOT_MET"],
          }),
        ],
      },
      [DL]: EMPTY_LEAGUE,
    });

    renderSection();

    expect(await screen.findByText("Dawid Zieliński")).toBeInTheDocument();
    expect(
      screen.getByText("Brakuje placementu do progu (wymagane: 2)"),
    ).toBeInTheDocument();
    // Nagroda przy niespełnionym progu jest WARUNKOWA — sucha kwota obiecywałaby
    // pieniądze, których ta osoba dziś nie dostaje.
    expect(screen.getByText(/po spełnieniu warunku/)).toBeInTheDocument();
    // Jedna osoba w rankingu NIE zwija podium do jednej kolumny: brakujące
    // miejsca zostają jako „Wolne miejsce". Znikająca kolumna rozjeżdża słupki
    // i czyta się jak dane, które się nie doczytały.
    expect(screen.getAllByText("Wolne miejsce")).toHaveLength(2);
  });

  it("pusty ranking to pusty stan, nie awaria", async () => {
    respond({
      [RECRUITER]: { ...RECRUITER_LEAGUE, top3: [], full_ranking: [] },
      [DL]: EMPTY_LEAGUE,
    });

    renderSection();

    // `findAllByText` wraca po PIERWSZYM trafieniu, a karty jadą na osobnych
    // zapytaniach — bez `waitFor` test sprawdzałby stan, w którym druga liga
    // jeszcze się ładuje.
    await waitFor(() =>
      expect(screen.getAllByText("Brak wyników w tym kwartale")).toHaveLength(
        2,
      ),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Spróbuj ponownie/ }),
    ).not.toBeInTheDocument();
  });

  it("awaria pokazuje komunikat z ponowieniem, nie pustkę", async () => {
    respond({ [RECRUITER]: httpError(500), [DL]: EMPTY_LEAGUE });

    renderSection();

    const alert = await screen.findByRole("alert");
    expect(
      within(alert).getByRole("button", { name: /Spróbuj ponownie/ }),
    ).toBeInTheDocument();
    // Awaria jednej ligi nie może udawać, że w niej po prostu nikogo nie ma:
    // pusty stan zostaje DOKŁADNIE jeden — ten należący do drugiej ligi.
    await waitFor(() =>
      expect(screen.getAllByText("Brak wyników w tym kwartale")).toHaveLength(
        1,
      ),
    );
  });

  it("403 mówi o uprawnieniach, a nie o braku danych", async () => {
    respond({ [RECRUITER]: httpError(403), [DL]: EMPTY_LEAGUE });

    renderSection();

    expect(
      await screen.findByText(/nie ma dostępu do sekcji/),
    ).toBeInTheDocument();
  });
});
