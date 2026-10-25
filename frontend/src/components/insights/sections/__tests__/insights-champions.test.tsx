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
import { currentQuarterKey } from "@/lib/insights-races-api";

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
    // Runda 8 (LEAGUE): punkty „za rozmowę" liczy rozmowa u klienta, nie QC CV.
    expect(screen.getByText(/Rozmowa u klienta/)).toBeInTheDocument();
    expect(screen.queryByText(/Interview/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/Wymagane minimum 2 placementy w kwartale/),
    ).toBeInTheDocument();
  });

  it("nagroda stoi pod SWOIM miejscem podium (audyt 24.09.2026)", async () => {
    // Podium jest ułożone 2-1-3; osobny rząd nagród 1-2-3 stawiał pod
    // 2. miejscem „1. miejsce 5000 zł”.
    respond({ [RECRUITER]: RECRUITER_LEAGUE, [DL]: EMPTY_LEAGUE });
    renderSection();

    const annaColumn = (await screen.findByText("Anna Kowalska")).closest("li");
    const bartekColumn = screen.getByText("Bartek Nowak").closest("li");
    expect(annaColumn).not.toBeNull();
    expect(bartekColumn).not.toBeNull();
    const annaPrize = within(annaColumn as HTMLElement).getByTestId(
      "league-prize-1",
    );
    expect(annaPrize).toHaveTextContent("1. miejsce");
    const bartekPrize = within(bartekColumn as HTMLElement).getByTestId(
      "league-prize-2",
    );
    expect(bartekPrize).toHaveTextContent("2. miejsce");
    // Kafel nagrody dzieli kolumnę (i kolejność wizualną) z miejscem podium.
    expect((annaColumn as HTMLElement).className).toContain("order-2");
    expect((bartekColumn as HTMLElement).className).toContain("order-1");
  });

  it("remis na płatnym miejscu = „Remis do rozstrzygnięcia”, bez kwoty (R3-13)", async () => {
    // Podium na żywo liczy ta sama funkcja co zamrożenie (`award_order`):
    // miejsca objęte remisem nie mają kwoty, dopóki admin nie zdecyduje.
    const tied = {
      ...RECRUITER_LEAGUE,
      top3: [
        entry({ prize_pln: 0, tied: true }),
        entry({
          user_id: 2,
          name: "Bartek Nowak",
          rank: 2,
          metric_value: 480,
          prize_pln: 0,
          tied: true,
        }),
        entry({
          user_id: 3,
          name: "Celina Wójcik",
          rank: 3,
          metric_value: 205,
          prize_pln: 2000,
        }),
      ],
    };
    respond({ [RECRUITER]: tied, [DL]: EMPTY_LEAGUE });
    renderSection();

    const annaColumn = (await screen.findByText("Anna Kowalska")).closest("li");
    const celinaColumn = screen.getByText("Celina Wójcik").closest("li");
    expect(
      within(annaColumn as HTMLElement).getByTestId("league-tie-1"),
    ).toHaveTextContent("Remis do rozstrzygnięcia");
    expect(screen.getByTestId("league-tie-2")).toBeInTheDocument();
    expect(screen.queryByTestId("league-tie-3")).not.toBeInTheDocument();
    expect(
      within(celinaColumn as HTMLElement).queryByText("Remis do rozstrzygnięcia"),
    ).not.toBeInTheDocument();
  });

  it("Liga DL mówi, jak liczy hit ratio (kwartał, zamknięte rekrutacje)", async () => {
    respond({ [RECRUITER]: RECRUITER_LEAGUE, [DL]: {
      ...EMPTY_LEAGUE,
      top3: [entry({ role: "delivery_lead", hit_ratio: 30.2, requests: 126 })],
      full_ranking: [entry({ role: "delivery_lead", hit_ratio: 30.2, requests: 126 })],
    } });
    renderSection();
    expect(
      await screen.findByText(/rekrutacje zamknięte w tym kwartale/),
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

  it("lista pod podium bierze numer z serwera — niezakwalifikowany bez „#1” (R4-14)", async () => {
    // Serwer (`award_ranked_rows`): kolejność nagrodowa 1..n, potem osoby bez
    // miejsca (`rank: null`). Do 25.09.2026 numer brano z pozycji w liście
    // i niezakwalifikowany lider oraz zwycięzca podium mieli oba „#1”.
    const podium = RECRUITER_LEAGUE.top3;
    respond({
      [RECRUITER]: {
        ...RECRUITER_LEAGUE,
        // Kolejność listy nie niesie numeru — o miejscu mówi wyłącznie `rank`.
        full_ranking: [
          entry({
            user_id: 4,
            name: "Dawid Zieliński",
            rank: null,
            prize_pln: null,
            metric_value: 900,
            qualified: false,
            required_placements: 2,
            disqualification_reasons: ["MIN_PLACEMENTS_NOT_MET"],
          }),
          ...podium,
          entry({ user_id: 5, name: "Ewa Mazur", rank: 4, metric_value: 150 }),
        ],
      },
      [DL]: EMPTY_LEAGUE,
    });

    renderSection();

    const dawid = (await screen.findByText(/Dawid Zieliński/)).closest("li");
    const ewa = screen.getByText(/Ewa Mazur/).closest("li");
    expect(within(dawid as HTMLElement).queryByText("#1")).not.toBeInTheDocument();
    expect(within(dawid as HTMLElement).getByText("—")).toBeInTheDocument();
    expect(within(ewa as HTMLElement).getByText("#4")).toBeInTheDocument();
    expect(screen.queryAllByText("#1")).toHaveLength(0);
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

// ─────────────────────────────────────────────────────────────────────────────
// Okresy z przeszłości (decyzja Artura 15.10.2026): Q1–Q3 2026 rozliczone
// z DynaReportera, Q4 2026 mieszany. Pola zamknięcia są opcjonalne — starszy
// backend ich nie zna.
// ─────────────────────────────────────────────────────────────────────────────

const Q2_RECRUITER =
  "/api/competitions/current?type=quarterly_champions_recruiter&period=Q2%202026";
const Q2_DL =
  "/api/competitions/current?type=quarterly_champions_dl&period=Q2%202026";

function renderSectionFor(period: string | null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ChampionsSection period={period} />
    </QueryClientProvider>,
  );
}

const DR_NOTE =
  "Wynik z DynaReportera — rozliczony przy przejściu na NEXUS (12.10.2026).";

const FROZEN_Q2 = {
  ...RECRUITER_LEAGUE,
  period: "Q2 2026",
  is_frozen: true,
  days_remaining: null,
  closure_status: "frozen",
  source: "dynareporter",
  source_note: DR_NOTE,
};

// ─────────────────────────────────────────────────────────────────────────────
// Liga DL od Q4 2026 (decyzja Artura 25.10.2026): ranking po hit ratio, bez
// nagród. Kwartały do Q3 2026 zostają w starym układzie (placementy, kwoty).
// ─────────────────────────────────────────────────────────────────────────────

function dlEntry(over: Record<string, unknown> = {}) {
  return entry({ role: "delivery_lead", prize_pln: 0, ...over });
}

const DL_HIT_RATIO_LEAGUE = {
  ...EMPTY_LEAGUE,
  period: "Q4 2026",
  prize_pool_pln: null,
  quarterly_prizes_pln: null,
  requirement:
    "Miejsce w klasyfikacji: minimum 3 placementy i 5 zamkniętych rekrutacji w kwartale. Liga DL nie ma nagród.",
  top3: [
    dlEntry({ user_id: 31, name: "Iza Pawlak", metric_value: 4, hit_ratio: 36.4, requests: 11, rank: 1 }),
    dlEntry({ user_id: 32, name: "Paweł Gil", metric_value: 6, hit_ratio: 30, requests: 20, rank: 2 }),
  ],
  full_ranking: [
    dlEntry({ user_id: 31, name: "Iza Pawlak", metric_value: 4, hit_ratio: 36.4, requests: 11, rank: 1 }),
    dlEntry({ user_id: 32, name: "Paweł Gil", metric_value: 6, hit_ratio: 30, requests: 20, rank: 2 }),
    dlEntry({
      user_id: 33,
      name: "Ola Sowa",
      metric_value: 2,
      hit_ratio: 50,
      requests: 4,
      rank: null,
      prize_pln: null,
      qualified: false,
      required_placements: 3,
      required_closed_requests: 5,
      disqualification_reasons: ["MIN_PLACEMENTS_NOT_MET", "MIN_CLOSED_REQUESTS_NOT_MET"],
    }),
  ],
};

describe("ChampionsSection — Liga DL po hit ratio (od Q4 2026)", () => {
  it("wynikiem jest hit ratio, a pod nim placementy i zamknięte rekrutacje", async () => {
    respond({ [RECRUITER]: RECRUITER_LEAGUE, [DL]: DL_HIT_RATIO_LEAGUE });
    renderSection();
    expect(await screen.findByText("Iza Pawlak")).toBeInTheDocument();
    expect(screen.getByText("Ranking Delivery Leadów po hit ratio · bez nagród")).toBeInTheDocument();
    expect(screen.getByText("4 placem. / 11 zamkn.")).toBeInTheDocument();
    // Więcej placementów, ale niższy procent — drugie miejsce.
    expect(screen.getByText("6 placem. / 20 zamkn.")).toBeInTheDocument();
  });

  it("bez nagród: żadnych kafli z kwotą przy podium ligi DL", async () => {
    respond({ [RECRUITER]: RECRUITER_LEAGUE, [DL]: DL_HIT_RATIO_LEAGUE });
    renderSection();
    await screen.findByText("Iza Pawlak");
    // Kafle kwot ma tylko Liga Rekrutacja (trzy miejsca).
    expect(screen.getAllByTestId(/^league-prize-/)).toHaveLength(3);
    expect(screen.getByText(/Liga DL nie ma nagród — to statystyka/)).toBeInTheDocument();
  });

  it("niespełniony próg zamkniętych rekrutacji jest nazwany z liczbą", async () => {
    respond({ [RECRUITER]: RECRUITER_LEAGUE, [DL]: DL_HIT_RATIO_LEAGUE });
    renderSection();
    expect(await screen.findByText("Ola Sowa")).toBeInTheDocument();
    expect(
      screen.getByText(/Brakuje placementu do progu \(wymagane: 3\) · Za mało zamkniętych rekrutacji \(wymagane: 5\)/),
    ).toBeInTheDocument();
  });

  it("kwartał sprzed Q4 2026 dalej pokazuje placementy i kwoty, którymi go rozliczono", async () => {
    respond({
      [Q2_RECRUITER]: FROZEN_Q2,
      [Q2_DL]: {
        ...EMPTY_LEAGUE,
        period: "Q2 2026",
        top3: [dlEntry({ metric_value: 23, hit_ratio: null, requests: 0, prize_pln: 5000 })],
        full_ranking: [dlEntry({ metric_value: 23, hit_ratio: null, requests: 0, prize_pln: 5000 })],
      },
    });
    renderSectionFor("Q2 2026");
    expect(await screen.findByText("Kwartalne podium Delivery Leadów")).toBeInTheDocument();
    expect(await screen.findAllByText("placementów")).not.toHaveLength(0);
  });
});

describe("ChampionsSection — wybrany kwartał", () => {
  it("bez okresu pyta dokładnie jak dotąd, z okresem dokleja `period` z zakodowaną spacją", async () => {
    respond({
      [Q2_RECRUITER]: FROZEN_Q2,
      [Q2_DL]: { ...EMPTY_LEAGUE, period: "Q2 2026" },
    });
    renderSectionFor("Q2 2026");

    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
    const urls = mocks.get.mock.calls.map((call) => call[0]);
    expect(urls).toContain(Q2_RECRUITER);
    expect(urls).toContain(Q2_DL);
    expect(urls).not.toContain(RECRUITER);
  });

  it("zamrożony kwartał: „Zamknięte” zamiast odliczania i zdanie o źródle z serwera", async () => {
    respond({
      [Q2_RECRUITER]: FROZEN_Q2,
      [Q2_DL]: {
        ...EMPTY_LEAGUE,
        period: "Q2 2026",
        is_frozen: true,
        days_remaining: null,
        source: "dynareporter",
        source_note: DR_NOTE,
      },
    });
    renderSectionFor("Q2 2026");

    await waitFor(() => expect(screen.getAllByText("Zamknięte")).toHaveLength(2));
    expect(screen.queryByText(/Zostało/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 dni/)).not.toBeInTheDocument();
    expect(screen.getAllByText(DR_NOTE)).toHaveLength(2);
  });

  it("miniony kwartał ze starszego backendu (bez `is_frozen`) nie odlicza dni dzisiejszego kwartału", async () => {
    // Starszy backend liczy `days_remaining` z dzisiaj — dla Q2 opisywałby Q4.
    const { is_frozen: _ignored, ...withoutFrozen } = RECRUITER_LEAGUE;
    respond({
      [Q2_RECRUITER]: { ...withoutFrozen, period: "Q2 2026", days_remaining: 77 },
      [Q2_DL]: { ...EMPTY_LEAGUE, period: "Q2 2026", days_remaining: 77 },
    });
    renderSectionFor("Q2 2026");

    await waitFor(() => expect(screen.getAllByText("Zakończony")).toHaveLength(2));
    expect(screen.queryByText(/Zostało/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("competition-source-note")).not.toBeInTheDocument();
  });

  it("okres mieszany pokazuje zdanie o źródle i dalej odlicza dni", async () => {
    const note = "1–11.10 z DynaReportera, od 12.10 z NEXUS-a.";
    respond({
      // Trwający kwartał — okres liczony z zegara, żeby test nie zestarzał się
      // razem z kalendarzem.
      [RECRUITER]: {
        ...RECRUITER_LEAGUE,
        period: currentQuarterKey(),
        source: "mixed",
        source_note: note,
      },
      [DL]: { ...EMPTY_LEAGUE, period: currentQuarterKey() },
    });
    renderSection();

    expect(await screen.findByText(note)).toBeInTheDocument();
    expect(screen.getByTestId("competition-source-note").className).toContain(
      "bg-primary/10",
    );
    await waitFor(() =>
      expect(screen.getAllByText("Zostało 12 dni")).toHaveLength(2),
    );
  });

  it("remis do decyzji admina jest widoczny nad podium", async () => {
    respond({
      [Q2_RECRUITER]: { ...FROZEN_Q2, closure_status: "tie_pending" },
      [Q2_DL]: { ...EMPTY_LEAGUE, period: "Q2 2026" },
    });
    renderSectionFor("Q2 2026");

    expect(
      await screen.findByText("Remis — o miejscu zdecyduje admin"),
    ).toBeInTheDocument();
  });

  it("zamknięty kwartał bez zwycięzcy mówi to wprost — z rankingiem i bez", async () => {
    respond({
      // Ranking jest, ale nikt nie spełnił warunku.
      [Q2_RECRUITER]: {
        ...FROZEN_Q2,
        closure_status: "no_winner",
        top3: [],
        full_ranking: [
          entry({
            rank: null,
            prize_pln: null,
            qualified: false,
            disqualification_reasons: ["MIN_PLACEMENTS_NOT_MET"],
          }),
        ],
      },
      // Pusty ranking: tytuł pustego stanu mówi o braku zwycięzcy.
      [Q2_DL]: {
        ...EMPTY_LEAGUE,
        period: "Q2 2026",
        is_frozen: true,
        days_remaining: null,
        closure_status: "no_winner",
      },
    });
    renderSectionFor("Q2 2026");

    await waitFor(() =>
      expect(screen.getAllByText("Brak zwycięzcy w tym okresie")).toHaveLength(2),
    );
    expect(screen.getByTestId("competition-no-winner")).toBeInTheDocument();
    expect(screen.getByText(/Anna Kowalska/)).toBeInTheDocument();
    expect(screen.queryByText("Brak wyników w tym kwartale")).not.toBeInTheDocument();
  });

  it("awaria minionego kwartału to nadal błąd z ponowieniem, nie „brak zwycięzcy”", async () => {
    respond({
      [Q2_RECRUITER]: httpError(500),
      [Q2_DL]: { ...EMPTY_LEAGUE, period: "Q2 2026" },
    });
    renderSectionFor("Q2 2026");

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.queryByText("Brak zwycięzcy w tym okresie"),
    ).not.toBeInTheDocument();
  });
});
