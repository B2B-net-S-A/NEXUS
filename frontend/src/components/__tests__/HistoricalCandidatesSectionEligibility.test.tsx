/**
 * Pusty stan sekcji musi odróżniać „nie było historii” od „historia jest,
 * ale zablokowana dla tego klienta”.
 *
 * Bramka dopuszczalności na `/jobs/{id}/candidates-from-similar` (sierpień
 * 2026) wycina z tej sekcji jej najbogatszą populację — ludzi rozważanych już
 * u TEGO klienta, czyli tych z aktywną blacklistą, NDA, konfliktem
 * konkurencyjnym albo wetem hiring managera. Bez rozgałęzienia poniżej zdanie
 * „Brak kandydatów w historii podobnych projektów.” stałoby się nieprawdą
 * dokładnie u klientów z najgęstszą historią.
 *
 * Testy jadą przez PRAWDZIWY komponent i obietnicę `historicalCandidatesApi`,
 * więc dowód idzie tą samą ścieżką, którą zmieniamy — nie mockujemy warstwy
 * renderującej pusty stan.
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

const EMPTY_TEXT = "Brak kandydatów w historii podobnych projektów.";
const BLOCKED_TEXT = /wszyscy są zablokowani dla tego klienta/;

function emptyResponse(meta: Record<string, unknown>) {
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
        reason_if_empty: null,
        ...meta,
      },
    },
  };
}

function renderSection() {
  const client = new QueryClient({
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

describe("HistoricalCandidatesSection — pusty stan a bramka dopuszczalności", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("wszyscy wycięci przez bramkę → mówi o blokadzie, nie o braku historii", async () => {
    mocks.forJob.mockResolvedValue(
      emptyResponse({
        hidden_ineligible: 3,
        reason_if_empty: "all_hidden_by_eligibility",
      }),
    );

    renderSection();

    expect(await screen.findByText(BLOCKED_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument();
  });

  it("nie ujawnia ILU jest zablokowanych — to byłaby wyrocznia na NDA", async () => {
    mocks.forJob.mockResolvedValue(
      emptyResponse({
        hidden_ineligible: 3,
        reason_if_empty: "all_hidden_by_eligibility",
      }),
    );

    renderSection();

    const notice = await screen.findByText(BLOCKED_TEXT);
    // Licznik mówiłby rekruterowi, ilu ludzi u tego klienta istnieje, a nie
    // wolno mu ich zobaczyć. Renderujemy fakt blokady, nie jej rozmiar.
    expect(notice.textContent ?? "").not.toMatch(/\d/);
  });

  it("brak ukrytych → dotychczasowy tekst zostaje bez zmian", async () => {
    mocks.forJob.mockResolvedValue(emptyResponse({ hidden_ineligible: 0 }));

    renderSection();

    expect(await screen.findByText(EMPTY_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(BLOCKED_TEXT)).not.toBeInTheDocument();
  });

  it("starszy backend bez pola → tekst dotychczasowy, bez wyjątku", async () => {
    // Kontrakt jest addytywny: brak klucza ma być zerem, nie awarią renderu.
    mocks.forJob.mockResolvedValue(emptyResponse({}));

    renderSection();

    expect(await screen.findByText(EMPTY_TEXT)).toBeInTheDocument();
  });
});
