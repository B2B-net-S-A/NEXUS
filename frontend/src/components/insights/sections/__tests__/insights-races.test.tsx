/**
 * Wyścigi miesięczne + Hall of Fame na `/insights`.
 *
 * Reguły pod ochroną — każda opisuje defekt, który da się popełnić refaktorem
 * wyglądającym na kosmetyczny:
 *
 * 1. **Plakietka „X/dzień" NIE zgaduje mianownika.** Bez dni roboczych z
 *    COMPASSA renderuje „—" i mówi dlaczego. Test sprawdza także, że na ekranie
 *    nie pojawia się liczba, którą dałoby się wyprodukować dzieleniem przez
 *    stałą (`required_verifications / 4`) — bo dokładnie taka „poprawka"
 *    przywróciłaby defekt, dla którego moduł dni roboczych powstał.
 * 2. **Niezakwalifikowany i wykluczony ZOSTAJĄ na liście**, oznaczeni powodem.
 *    Ukrycie zamienia „próg niespełniony" w „zero wyniku".
 * 3. **Awaria ≠ pustka.** 500 renderuje komunikat z ponowieniem, nie „brak
 *    wyników"; pusta historia mówi „nikomu jeszcze nie przyznano nagrody".
 * 4. **Zamknięty miesiąc nie odlicza dni.** `days_remaining` liczy się z
 *    „dzisiaj", nie z okresu, więc dla sierpnia oglądanego we wrześniu
 *    opisywałby wrzesień.
 * 5. **Zerowy mianownik → „—", nigdy 0%.** Backend podstawia tam `0.0`.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import { InsightsRaces } from "@/components/insights/sections/InsightsRaces";
import { InsightsHallOfFame } from "@/components/insights/sections/InsightsHallOfFame";
import {
  currentMonthKey,
  formatMonthPl,
  isClosedMonth,
  monthFromResolvedPeriod,
  perDayVerifications,
  precisionOf,
  type MonthlyRaceEntry,
} from "@/lib/insights-races-api";

const RACES = "/api/competitions/monthly-races";
const CURRENT = "/api/competitions/current";
const HISTORY = "/api/competitions/history";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

/** Odpowiedzi po ŚCIEŻCE — parametry jadą osobnym argumentem axiosa. */
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

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

function recEntry(over: Partial<MonthlyRaceEntry> = {}): MonthlyRaceEntry {
  return {
    user_id: 1,
    name: "Martyna Gołębska",
    metric_value: 42,
    rank: 1,
    excluded: false,
    role: "sourcer",
    verifications: 63,
    recommendations: 42,
    precision_pct: 66.7,
    // 4 × 20 dni roboczych — jedyna liczba w kopercie, z której dałoby się
    // „odtworzyć" mianownik. Testy pilnują, że nikt tego nie robi.
    required_verifications: 80,
    qualified: false,
    disqualification_reasons: [
      "MIN_VERIFICATIONS_NOT_MET",
      "MIN_PRECISION_NOT_MET",
    ],
    ...over,
  };
}

function placEntry(over: Partial<MonthlyRaceEntry> = {}): MonthlyRaceEntry {
  return {
    user_id: 9,
    name: "Marlena Rosół",
    metric_value: 4,
    rank: 1,
    excluded: false,
    role: "tac",
    ...over,
  };
}

function racesPayload(
  over: {
    period?: string;
    recommendations?: MonthlyRaceEntry[];
    placements?: MonthlyRaceEntry[];
    daysRemaining?: number | null;
  } = {},
) {
  const period = over.period ?? "2020-01";
  const prize = {
    amount_pln: 1500,
    name: "Voucher 1 500 PLN (Modivo, Douglas, Media Markt)",
  };
  return {
    recommendations: {
      period,
      days_remaining: over.daysRemaining ?? 5,
      prize,
      requirements: [
        "Wymóg: min. 4 weryfikacji/dzień roboczy w tym miesiącu",
        "Wymóg: min. 75% precision rate (rekomendacje / weryfikacje)",
        "Lider kwartalny wykluczony z nagrody miesięcznej",
      ],
      ranking: over.recommendations ?? [recEntry()],
      excluded_user_ids: [],
      qualified_leader: null,
    },
    placements: {
      period,
      days_remaining: over.daysRemaining ?? 5,
      prize,
      requirements: [
        "Minimum 2 placementy do kwalifikacji",
        "Lider kwartalny wykluczony z nagrody miesięcznej",
      ],
      ranking: over.placements ?? [placEntry()],
      excluded_user_ids: [],
      qualified_leader: null,
    },
  };
}

beforeEach(() => {
  mocks.get.mockReset();
});

// ─────────────────────────────────────────────────────────────────────────────
// Czyste funkcje — cała arytmetyka ekranu.
// ─────────────────────────────────────────────────────────────────────────────

describe("perDayVerifications", () => {
  it("bez dni roboczych zwraca null z powodem, NIE liczbę ze stałej", () => {
    const entry = recEntry({ verifications: 63, required_verifications: 80 });
    expect(perDayVerifications(entry)).toEqual({
      value: null,
      reason: "no_workday_data",
    });
  });

  it("dzieli przez dni robocze z COMPASSA, gdy są", () => {
    const result = perDayVerifications(
      recEntry({ verifications: 62, workdays: 20 }),
    );
    expect(result.reason).toBe("ok");
    expect(result.value).toBeCloseTo(3.1, 5);
  });

  it("ufa gotowemu `per_day`, gdy backend go policzy", () => {
    expect(
      perDayVerifications(
        recEntry({ per_day: 2.3, workdays: 20, verifications: 1 }),
      ),
    ).toEqual({ value: 2.3, reason: "ok" });
  });

  it("zero dni roboczych to osobny powód — dzielenie przez zero nie jest oceną", () => {
    expect(perDayVerifications(recEntry({ workdays: 0 }))).toEqual({
      value: null,
      reason: "zero_workdays",
    });
  });
});

describe("precisionOf", () => {
  it("zeruje się tylko wtedy, gdy naprawdę było zero rekomendacji", () => {
    expect(precisionOf(recEntry({ verifications: 10, precision_pct: 0 }))).toBe(
      0,
    );
  });

  it("przy zerowych weryfikacjach zwraca null, mimo `0.0` z backendu", () => {
    // `competitions.py`: `round(...) if verified else 0.0` — zero jest tam
    // zaślepką, nie wynikiem.
    expect(
      precisionOf(recEntry({ verifications: 0, precision_pct: 0 })),
    ).toBeNull();
  });
});

describe("formatMonthPl / isClosedMonth / monthFromResolvedPeriod", () => {
  it("formatuje miesiąc po polsku, wielką literą", () => {
    expect(formatMonthPl("2026-08")).toBe("Sierpień 2026");
  });

  it("nierozpoznany okres (kwartał) zostawia bez zmian", () => {
    expect(formatMonthPl("Q3 2026")).toBe("Q3 2026");
  });

  it("miesiąc z przeszłości jest zamknięty, bieżący nie", () => {
    expect(isClosedMonth("2020-01")).toBe(true);
    expect(isClosedMonth(currentMonthKey())).toBe(false);
  });

  it("bierze miesiąc TYLKO z okna miesięcznego rozwiązanego przez serwer", () => {
    expect(
      monthFromResolvedPeriod({
        kind: "month",
        start: "2026-08-01T00:00:00+02:00",
      }),
    ).toBe("2026-08");
    // Kwartał ma trzy miesiące — podstawienie pierwszego byłoby cichą podmianą
    // okresu pod nagłówkiem „Q3".
    expect(
      monthFromResolvedPeriod({
        kind: "quarter",
        start: "2026-07-01T00:00:00+02:00",
      }),
    ).toBeNull();
    expect(monthFromResolvedPeriod(null)).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Wyścigi
// ─────────────────────────────────────────────────────────────────────────────

describe("InsightsRaces", () => {
  it("bez dni roboczych pokazuje myślnik na dzień i powód, zamiast liczby ze stałej", async () => {
    respond({ [RACES]: racesPayload() });
    renderWithClient(<InsightsRaces month="2020-01" />);

    expect(await screen.findByText("Wyścig Rekomendacji")).toBeInTheDocument();
    expect(
      screen.getAllByText(/brak danych o dniach roboczych/).length,
    ).toBeGreaterThan(0);

    // 63 weryfikacji / (80 wymaganych ÷ 4 na dzień) = 3.2 — liczba, którą
    // wyprodukowałoby dzielenie przez stałą. Nie wolno jej tu zobaczyć.
    expect(screen.queryByText(/3[.,]2\/dzień/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\d+[.,]\d+\/dzień/)).not.toBeInTheDocument();
  });

  it("z dniami roboczymi z COMPASSA zapala plakietkę", async () => {
    respond({
      [RACES]: racesPayload({
        recommendations: [
          recEntry({
            verifications: 62,
            workdays: 20,
            workdays_source: "compass",
          }),
        ],
      }),
    });
    renderWithClient(<InsightsRaces month="2020-01" />);

    expect(await screen.findByText("3.1/dzień")).toBeInTheDocument();
  });

  it("niezakwalifikowany zostaje na liście z powodem", async () => {
    respond({ [RACES]: racesPayload() });
    renderWithClient(<InsightsRaces month="2020-01" />);

    expect(await screen.findByText("Martyna Gołębska")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Za mało weryfikacji · Za niska skuteczność rekomendacji",
      ),
    ).toBeInTheDocument();
    // Surowe liczby progu — bez przeliczania na tempo dzienne.
    expect(
      screen.getByText(/63 \/ 80 wymaganych weryfikacji/),
    ).toBeInTheDocument();
  });

  it("lider kwartału jest oznaczony, a nie usunięty z rankingu", async () => {
    respond({
      [RACES]: racesPayload({
        recommendations: [
          recEntry({
            excluded: true,
            qualified: true,
            disqualification_reasons: [],
          }),
        ],
      }),
    });
    renderWithClient(<InsightsRaces month="2020-01" />);

    expect(await screen.findByText("Martyna Gołębska")).toBeInTheDocument();
    expect(screen.getByText(/Lider kwartału/)).toBeInTheDocument();
  });

  it("przy zerowych weryfikacjach precision to myślnik, nie 0%", async () => {
    respond({
      [RACES]: racesPayload({
        recommendations: [
          recEntry({
            verifications: 0,
            precision_pct: 0,
            qualified: true,
            disqualification_reasons: [],
          }),
        ],
      }),
    });
    renderWithClient(<InsightsRaces month="2020-01" />);

    expect(await screen.findByText("Martyna Gołębska")).toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("zamknięty miesiąc dostaje chip Zakończony, bez odliczania", async () => {
    respond({ [RACES]: racesPayload({ period: "2020-01", daysRemaining: 5 }) });
    renderWithClient(<InsightsRaces month="2020-01" />);

    expect(await screen.findAllByText("Zakończony")).toHaveLength(2);
    expect(screen.queryByText(/Zostało/)).not.toBeInTheDocument();
    expect(screen.getAllByText("Styczeń 2020").length).toBe(2);
  });

  it("trwający miesiąc odlicza dni zamiast chipa", async () => {
    const now = currentMonthKey();
    respond({ [RACES]: racesPayload({ period: now, daysRemaining: 5 }) });
    renderWithClient(<InsightsRaces month={now} />);

    expect(await screen.findAllByText("Zostało 5 dni")).toHaveLength(2);
    expect(screen.queryByText("Zakończony")).not.toBeInTheDocument();
  });

  it("awaria renderuje komunikat z ponowieniem, nie pustkę", async () => {
    respond({ [RACES]: httpError(500) });
    renderWithClient(<InsightsRaces month="2020-01" />);

    expect(
      await screen.findByText(/Nie udało się pobrać danych sekcji/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Brak wyników w tym miesiącu/),
    ).not.toBeInTheDocument();
  });

  it("pusty ranking to spokojny stan, osobny dla każdego wyścigu", async () => {
    respond({
      [RACES]: racesPayload({ recommendations: [], placements: [placEntry()] }),
    });
    renderWithClient(<InsightsRaces month="2020-01" />);

    expect(await screen.findByText("Marlena Rosół")).toBeInTheDocument();
    expect(screen.getAllByText("Brak wyników w tym miesiącu")).toHaveLength(1);
  });

  it("mówi wprost, kogo w Wyścigu Placementów NIE MA na liście", async () => {
    respond({ [RACES]: racesPayload() });
    renderWithClient(<InsightsRaces month="2020-01" />);

    expect(
      await screen.findByText(/wyłącznie osoby z min\. 2 placementami/),
    ).toBeInTheDocument();
  });

  it("stopka opisuje remis tak, jak rozstrzyga go silnik (nie marżą)", async () => {
    respond({ [RACES]: racesPayload() });
    renderWithClient(<InsightsRaces month="2020-01" />);

    const notes = await screen.findAllByText(
      /NEXUS nie rozstrzyga remisu marżą/,
    );
    expect(notes).toHaveLength(2);
  });

  it("przycisk Pokaż wszystkich odsłania resztę rankingu", async () => {
    const user = userEvent.setup();
    respond({
      [RACES]: racesPayload({
        placements: [1, 2, 3, 4].map((i) =>
          placEntry({
            user_id: i,
            rank: i,
            name: `Osoba ${i}`,
            metric_value: 5 - i,
          }),
        ),
      }),
    });
    renderWithClient(<InsightsRaces month="2020-01" />);

    expect(await screen.findByText("Osoba 1")).toBeInTheDocument();
    expect(screen.queryByText("Osoba 4")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Pokaż wszystkich \(4\)/ }),
    );
    expect(screen.getByText("Osoba 4")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Hall of Fame
// ─────────────────────────────────────────────────────────────────────────────

describe("InsightsHallOfFame", () => {
  const allTime = {
    type: "hall_of_fame",
    period: "all_time",
    top3: [],
    full_ranking: [
      { user_id: 1, name: "Marlena Rosół", metric_value: 23, is_active: true },
      { user_id: 2, name: "Michał Walasek", metric_value: 22, is_active: true },
      { user_id: 3, name: "Elza Grabińska", metric_value: 6, is_active: false },
    ],
    scope: {
      ranked_placements: 167,
      outside_role_placements: 147,
      unattributed_placements: 0,
      ranked_people: 12,
      roles: [
        "sourcer",
        "tac",
        "recruiter",
        "delivery_lead",
        "head_of_recruitment",
      ],
      attribution: "first_hired_per_candidate_job",
    },
  };

  it("pokazuje ranking all-time i podpisuje go jako NIE-listę zwycięzców", async () => {
    respond({
      [CURRENT]: allTime,
      [HISTORY]: { type: "monthly_recommendations", periods: [] },
    });
    renderWithClient(<InsightsHallOfFame />);

    expect(await screen.findByText("Marlena Rosół")).toBeInTheDocument();
    expect(
      screen.getByText(/To NIE jest lista zwycięzców/),
    ).toBeInTheDocument();
    // Serwer tnie ten ranking do PIĘCIU wierszy. Lista bez tej informacji
    // czyta się jako komplet, więc osoba na szóstym miejscu widzi, że „jej
    // nie ma w rankingu" — to ta sama klasa kłamstwa co przycięta lista
    // hiring managerów obok.
    expect(screen.getByText("TOP 5")).toBeInTheDocument();
    // Ten ranking liczy TAK SAMO jak „Analiza placementów" (definicja D2),
    // ale INACZEJ niż „Wyścig Placementów" obok, który wypłaca nagrodę.
    // Dwie sąsiadujące tabele z inną regułą muszą to powiedzieć — inaczej
    // różnica wygląda na błąd jednej z nich.
    expect(
      screen.getByText(/tak samo jak w „Analizie placementów"/),
    ).toBeInTheDocument();
    expect(screen.getByText("inaczej")).toBeInTheDocument();
  });

  it("zostawia byłego pracownika w rankingu, ale go OZNACZA", async () => {
    respond({
      [CURRENT]: allTime,
      [HISTORY]: { type: "monthly_recommendations", periods: [] },
    });
    renderWithClient(<InsightsHallOfFame />);

    // Ranking WSZECH CZASÓW — odejście z firmy nie cofa tego, co ktoś
    // osiągnął. Wycięcie wiersza kasowałoby dorobek wstecz, a wiersz bez
    // chipa sugerowałby, że ta osoba wciąż tu pracuje. Ta sama reguła co
    // w tabeli „Performance per osoba" dwie sekcje wyżej.
    expect(await screen.findByText("Elza Grabińska")).toBeInTheDocument();
    expect(screen.getByText("były pracownik")).toBeInTheDocument();
  });

  it("mówi, ile placementów stoi POZA rankingiem", async () => {
    respond({
      [CURRENT]: allTime,
      [HISTORY]: { type: "monthly_recommendations", periods: [] },
    });
    renderWithClient(<InsightsHallOfFame />);

    // Bez tego zdania TOP 5 czyta się jako całość bazy. Po przejściu na
    // atrybucję D2 poza rankingiem zostaje WIĘKSZOŚĆ placementów — domknięta
    // przez konta administracyjne, które nie rekrutują.
    await screen.findByText("Marlena Rosół");
    expect(screen.getByText("147")).toBeInTheDocument();
    expect(
      screen.getByText(/domkniętych spoza tych ról/),
    ).toBeInTheDocument();
  });

  it("nie dopisuje zdania o wykluczonych, gdy nic nie odpada", async () => {
    respond({
      [CURRENT]: {
        ...allTime,
        scope: { ...allTime.scope, outside_role_placements: 0 },
      },
      [HISTORY]: { type: "monthly_recommendations", periods: [] },
    });
    renderWithClient(<InsightsHallOfFame />);

    // Zero to nie jest informacja — zdanie „poza rankingiem: 0" dokładałoby
    // szumu tam, gdzie nie ma czego wyjaśniać.
    await screen.findByText("Marlena Rosół");
    expect(
      screen.queryByText(/domkniętych spoza tych ról/),
    ).toBeNull();
  });

  it("pusta historia mówi, że nikt nie zamknął okresu — nie udaje awarii", async () => {
    respond({
      [CURRENT]: allTime,
      [HISTORY]: { type: "monthly_recommendations", periods: [] },
    });
    renderWithClient(<InsightsHallOfFame />);

    expect(
      await screen.findByText(
        /Żaden okres tego konkursu nie został jeszcze zamknięty/,
      ),
    ).toBeInTheDocument();
  });

  it("renderuje zamrożone podium z okresem i nagrodą", async () => {
    respond({
      [CURRENT]: allTime,
      [HISTORY]: {
        type: "monthly_recommendations",
        periods: [
          {
            period: "2026-08",
            top3: [
              {
                rank: 1,
                user_id: 5,
                user_name: "Wiktoria Deneka",
                metric_value: 39,
                points: null,
                prize_pln: 1500,
                created_at: "2026-09-01T08:00:00Z",
              },
            ],
          },
        ],
      },
    });
    renderWithClient(<InsightsHallOfFame />);

    expect(await screen.findByText("Sierpień 2026")).toBeInTheDocument();
    const row = screen
      .getByText("Wiktoria Deneka")
      .closest("li") as HTMLElement;
    expect(within(row).getByText(/1500|1 500/)).toBeInTheDocument();
  });

  it("awaria historii nie wygasza rankingu all-time", async () => {
    respond({ [CURRENT]: allTime, [HISTORY]: httpError(500) });
    renderWithClient(<InsightsHallOfFame />);

    expect(await screen.findByText("Marlena Rosół")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Nie udało się pobrać danych sekcji .Hall of Fame — zamknięte okresy/,
      ),
    ).toBeInTheDocument();
  });

  it("403 na historii mówi o uprawnieniach, nie o braku danych", async () => {
    respond({ [CURRENT]: allTime, [HISTORY]: httpError(403) });
    renderWithClient(<InsightsHallOfFame />);

    expect(await screen.findByText(/Dane NIE są puste/)).toBeInTheDocument();
  });
});
