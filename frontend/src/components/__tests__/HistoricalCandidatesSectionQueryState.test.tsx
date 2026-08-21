/**
 * „Kandydaci z podobnych projektów”: sekcja NIE znika (audyt F-20).
 *
 * Do sierpnia 2026 komponent miał dwa `return null` — jeden na `query.isError`,
 * drugi na pusty wynik. Awaria i zero wyników dawały ten sam efekt: całkowity
 * brak sekcji w DOM-ie. Rekruter zgłaszał „zniknęła mi sekcja”, a deep link
 * `?tab=similar` z powiadomienia prowadził do kotwicy, której nie było.
 *
 * Test odrzuca / rozwiązuje obietnicę `historicalCandidatesApi.forJob`, więc
 * idzie dokładnie tą ścieżką, na której siedział defekt — nie mockuje warstwy
 * renderowania, która była zepsuta.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  forJob: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  historicalCandidatesApi: {
    forJob: (...args: unknown[]) => mocks.forJob(...args),
  },
}));

vi.mock("@/lib/candidate-search-api", () => ({
  proposalsBulkApi: { add: vi.fn() },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { HistoricalCandidatesSection } from "@/components/HistoricalCandidatesSection";

const HEADING = "Kandydaci z podobnych projektów";
const EMPTY_TEXT = "Brak kandydatów w historii podobnych projektów.";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function emptyResponse() {
  return {
    data: {
      job_id: 5,
      tier_used: "primary",
      similar_jobs: [],
      candidates: [],
      meta: {
        tier_a_count: 0,
        tier_b_count: 0,
        total_sources: 0,
        reason_if_empty: "no_similar_jobs",
      },
    },
  };
}

function renderSection() {
  const client = new QueryClient({
    // Zapytanie ma WŁASNE `retry: 1` (produkcyjne zachowanie, nie ruszamy go),
    // więc domyślne `retry: false` go nie zdejmie — zerujemy tylko opóźnienie
    // między próbami, żeby test nie czekał sekundy na drugie podejście.
    defaultOptions: {
      queries: { retry: false, retryDelay: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <HistoricalCandidatesSection jobId={5} />
    </QueryClientProvider>,
  );
}

describe("HistoricalCandidatesSection — stany zapytania", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("500 zostawia sekcję na miejscu i pokazuje awarię z ponowieniem", async () => {
    mocks.forJob.mockRejectedValue(httpError(500));

    renderSection();

    expect(
      await screen.findByText(/Nie udało się pobrać danych/),
    ).toBeInTheDocument();
    // Sam nagłówek to połowa fixa: bez niego deep link `?tab=similar`
    // prowadziłby donikąd.
    expect(screen.getByText(HEADING)).toBeInTheDocument();
    expect(screen.getByText("nie udało się pobrać")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Spróbuj ponownie/ }),
    ).toBeInTheDocument();
    // Awaria nie może udawać, że przeszukaliśmy historię i nikogo nie ma.
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 kandydatów z 0/)).not.toBeInTheDocument();
  });

  it("403 mówi o uprawnieniach, bez przycisku ponowienia", async () => {
    mocks.forJob.mockRejectedValue(httpError(403));

    renderSection();

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.getByText(HEADING)).toBeInTheDocument();
    expect(screen.getByText(/Historia NIE jest pusta/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Spróbuj ponownie/ }),
    ).not.toBeInTheDocument();
  });

  it("pusty wynik jest OSIĄGALNY — sekcja zostaje z komunikatem o braku", async () => {
    mocks.forJob.mockResolvedValue(emptyResponse());

    renderSection();

    // Ta gałąź była martwa: `if (query.isFetched && !hasCandidates) return null`
    // wycinał komponent sto linii wcześniej.
    expect(await screen.findByText(EMPTY_TEXT)).toBeInTheDocument();
    expect(screen.getByText(HEADING)).toBeInTheDocument();
    expect(
      screen.queryByText(/Nie udało się pobrać danych/),
    ).not.toBeInTheDocument();
  });
});
