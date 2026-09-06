/**
 * Awaria wyszukiwania nie może wyglądać na kokpicie jak pusty wynik.
 *
 * Backend liczy `meta.degraded` zbiorczo: jeśli warstwa semantyczna nie
 * odpowiedziała dla CHOĆ JEDNEGO konsultanta, cała lista jest niepełna. Do
 * 09.2026 `SeekingContractorsBoard` nie czytał `meta` w ogóle (grep po pliku
 * nie zwracał ani jednego trafienia), więc sygnał kończył się na granicy API:
 * rekruter widział wiersze z pustymi dopasowaniami i żadnego wyjaśnienia.
 *
 * Test idzie przez react-query i prawdziwy komponent, nie przez atrapę
 * renderowania — defekt siedział dokładnie w warstwie, którą mockowanie widoku
 * by ominęło.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  seekingContractors: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  recommendationsApi: {
    seekingContractors: (...args: unknown[]) => mocks.seekingContractors(...args),
  },
}));

// Karta wiersza i pasek filtrów mają własne, ciężkie zależności (Link, toasty,
// ikony) i nie są przedmiotem tego testu — liczy się to, co robi plansza
// z `meta`.
vi.mock("@/components/sourcing/ContractorMatchCard", () => ({
  ContractorMatchCard: () => <div data-testid="contractor-card" />,
}));
vi.mock("@/components/sourcing/RecommendationFiltersBar", () => ({
  RecommendationFiltersBar: () => <div />,
}));

import { SeekingContractorsBoard } from "@/components/sourcing/SeekingContractorsBoard";

const EMPTY_STATE_TEXT = "Brak konsultantów do ulokowania";
const DEGRADED_TITLE = /Kokpit jest niepełny/i;

function row(id: number) {
  return {
    candidate: {
      id,
      name: "Jan",
      lastname: `Kowalski-${id}`,
      email: null,
      location: null,
      competence_category: null,
      years_it_experience: null,
      availability_status: "actively_looking",
      champion: false,
      avatar_url: null,
    },
    source: "availability_status" as const,
    contract_end_date: null,
    current_client_id: null,
    // Pusto WŁAŚNIE dlatego, że wyszukiwanie padło — to jest ten wiersz,
    // który bez banera czyta się jak „nic dla tej osoby nie ma".
    top_matches: [],
    below_threshold_count: 0,
  };
}

function respond(body: Record<string, unknown>) {
  mocks.seekingContractors.mockResolvedValue({ data: body });
}

function renderBoard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SeekingContractorsBoard />
    </QueryClientProvider>,
  );
}

describe("SeekingContractorsBoard — stan awarii wyszukiwania", () => {
  beforeEach(() => {
    mocks.seekingContractors.mockReset();
  });

  it("mówi, że kokpit jest niepełny, gdy wyszukiwanie padło", async () => {
    respond({
      horizon_days: 30,
      total: 2,
      returned: 2,
      truncated: false,
      items: [row(1), row(2)],
      meta: { degraded: true, reason: "semantic_unavailable" },
    });

    renderBoard();

    expect(await screen.findByTestId("degraded-banner")).toBeInTheDocument();
    expect(screen.getByText(DEGRADED_TITLE)).toBeInTheDocument();
    // Wiersze zostają — konsultanci istnieją, nie policzyliśmy im dopasowań.
    expect(await screen.findAllByTestId("contractor-card")).toHaveLength(2);
  });

  it("przy awarii NIE twierdzi, że nie ma konsultantów", async () => {
    // Gałąź pustej listy nie może wygrać z awarią. „Brak konsultantów do
    // ulokowania" przy padniętym dostawcy jest zdaniem nieprawdziwym — i to
    // takim, po którym rekruter zamyka ekran i nie wraca.
    respond({
      horizon_days: 30,
      total: 0,
      returned: 0,
      truncated: false,
      items: [],
      meta: { degraded: true, reason: "semantic_unavailable" },
    });

    renderBoard();

    expect(await screen.findByTestId("degraded-banner")).toBeInTheDocument();
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
    expect(screen.queryByText(EMPTY_STATE_TEXT)).not.toBeInTheDocument();
  });

  it("normalny pusty wynik zostaje pustym wynikiem, bez alarmu", async () => {
    // Kontrola negatywna. Bez niej „naprawa" pokazująca baner zawsze przechodzi
    // na zielono, a każdy pusty horyzont wygląda jak awaria — czyli zamieniamy
    // jedno kłamstwo na drugie.
    respond({
      horizon_days: 30,
      total: 0,
      returned: 0,
      truncated: false,
      items: [],
      meta: { degraded: false, reason: "no_candidates" },
    });

    renderBoard();

    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    expect(screen.queryByTestId("degraded-banner")).not.toBeInTheDocument();
  });

  it("odpowiedź bez `meta` czyta się jak brak awarii", async () => {
    // Okno wdrożenia: przeglądarka może dostać odpowiedź ze starszego backendu,
    // który tego klucza nie niósł. Domyślne „awaria" zapaliłoby wtedy alarm na
    // każdym poprawnym, pustym horyzoncie.
    respond({
      horizon_days: 30,
      total: 0,
      returned: 0,
      truncated: false,
      items: [],
    });

    renderBoard();

    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    expect(screen.queryByTestId("degraded-banner")).not.toBeInTheDocument();
  });
});
