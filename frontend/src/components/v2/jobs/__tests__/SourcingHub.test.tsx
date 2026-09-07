import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * SourcingHub — rama źródeł kandydatów (krok 03 „Pozyskiwanie", program
 * „Flow w języku C2", PR 2/7). C2 i pełne komponenty za kartami
 * (HistoricalCandidatesSection, SuggestedCandidatesWidget,
 * RequestHistorySection) mają WŁASNE testy — tu mockujemy je jako stuby,
 * żeby sprawdzać wyłącznie logikę huba: karty, liczniki, klik → onTabChange,
 * stan awarii.
 */

const mocks = vi.hoisted(() => ({
  getMatches: vi.fn(),
  regenerate: vi.fn(),
  forJob: vi.fn(),
  postingsList: vi.fn(),
  shortlistList: vi.fn(),
  savedSearchesList: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  routerReplace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.routerReplace }),
  usePathname: () => "/jobs/7",
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("@/lib/api", () => ({
  matchingApi: { getMatches: (...args: unknown[]) => mocks.getMatches(...args) },
  postingsApi: { list: (...args: unknown[]) => mocks.postingsList(...args) },
  proposalsApi: { regenerate: (...args: unknown[]) => mocks.regenerate(...args) },
  historicalCandidatesApi: { forJob: (...args: unknown[]) => mocks.forJob(...args) },
}));

vi.mock("@/lib/candidate-search-api", () => ({
  shortlistApi: { list: (...args: unknown[]) => mocks.shortlistList(...args) },
  savedSearchesApi: { list: (...args: unknown[]) => mocks.savedSearchesList(...args) },
}));

vi.mock("@/components/v2/jobs/JobShortlist", () => ({
  jobShortlistQueryKey: (jobId: number) => ["job-shortlist", jobId],
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

vi.mock("@/components/HistoricalCandidatesSection", () => ({
  HistoricalCandidatesSection: ({ jobId }: { jobId: number }) => (
    <div data-testid="historical-mock">historical:{jobId}</div>
  ),
}));

vi.mock("@/components/SuggestedCandidatesWidget", () => ({
  SuggestedCandidatesWidget: ({ jobId }: { jobId: number }) => (
    <div data-testid="suggested-mock">suggested:{jobId}</div>
  ),
}));

vi.mock("@/components/RequestHistorySection", () => ({
  RequestHistorySection: ({ jobId }: { jobId: number }) => (
    <div data-testid="history-mock">history:{jobId}</div>
  ),
}));

import { SourcingHub } from "@/components/v2/jobs/SourcingHub";

function renderHub(overrides: Partial<React.ComponentProps<typeof SourcingHub>> = {}) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, retryDelay: 0 },
      mutations: { retry: false },
    },
  });
  const onTabChange = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <SourcingHub
        jobId={7}
        job={{ location: "Warszawa", client_id: 3, has_budget_hourly: true }}
        readOnly={false}
        onTabChange={onTabChange}
        {...overrides}
      >
        <div data-testid="c2-mock">C2 tutaj</div>
      </SourcingHub>
    </QueryClientProvider>,
  );
  return { onTabChange };
}

describe("SourcingHub", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getMatches.mockResolvedValue({
      data: {
        matches: [{}, {}, {}],
        meta: { hidden: { over_budget: 1, remote_only: 1 } },
      },
    });
    mocks.postingsList.mockResolvedValue({ data: [] });
    mocks.shortlistList.mockResolvedValue([]);
    mocks.savedSearchesList.mockResolvedValue([]);
    mocks.forJob.mockResolvedValue({
      data: {
        candidates: [{}, {}],
        similar_jobs: [{ similarity: 0.86 }],
        meta: {},
      },
    });
    mocks.regenerate.mockResolvedValue({ data: {} });
  });

  it("renderuje cztery karty źródeł i C2 bez zmian poniżej", async () => {
    renderHub();

    expect(await screen.findByTestId("sourcing-ai-matching-card")).toBeInTheDocument();
    expect(screen.getByTestId("sourcing-manual-search-card")).toBeInTheDocument();
    expect(screen.getByTestId("sourcing-similar-projects-card")).toBeInTheDocument();
    expect(screen.getByTestId("sourcing-portals-card")).toBeInTheDocument();
    // C2 (children) renderuje się bez zmian, niezależnie od stanu kart.
    expect(screen.getByTestId("c2-mock")).toBeInTheDocument();
    // Historia requestu (kompaktowa) zawsze pod ramą.
    expect(screen.getByTestId("history-mock")).toBeInTheDocument();
  });

  it("karta AI Matching liczy w rankingu / ukryto / shortlistę", async () => {
    renderHub();

    const card = await screen.findByTestId("sourcing-ai-matching-card");
    await waitFor(() => expect(mocks.getMatches).toHaveBeenCalledWith(7));

    await waitFor(() => {
      expect(within(card).getByText("3")).toBeInTheDocument(); // w rankingu
    });
    expect(within(card).getByText("2")).toBeInTheDocument(); // ukryto = 1 + 1
    expect(within(card).getByText("0")).toBeInTheDocument(); // shortlista pusta
    expect(within(card).getByText("w rankingu")).toBeInTheDocument();
    expect(within(card).getByText("ukryto")).toBeInTheDocument();
    expect(within(card).getByText("shortlista")).toBeInTheDocument();
  });

  it("karta Podobne projekty liczy kandydatów z candidates-from-similar", async () => {
    renderHub();

    const card = await screen.findByTestId("sourcing-similar-projects-card");
    await waitFor(() => expect(mocks.forJob).toHaveBeenCalledWith(7, {
      tier: "primary",
      limit: 20,
      include_negative: true,
    }));
    await waitFor(() => {
      expect(within(card).getByText("2")).toBeInTheDocument(); // kandydatów
    });
    expect(within(card).getByText("86%")).toBeInTheDocument(); // najbliższy request
  });

  it("klik na „Wyszukaj manualnie” i „Portale ogłoszeniowe” woła onTabChange", async () => {
    const { onTabChange } = renderHub();

    await userEvent.click(await screen.findByTestId("sourcing-manual-search-card"));
    expect(onTabChange).toHaveBeenCalledWith("manual-search");

    await userEvent.click(screen.getByTestId("sourcing-portals-card"));
    expect(onTabChange).toHaveBeenCalledWith("portals");

    // Nawigacyjne karty nie mutują nic — zero wywołań zapisu.
    expect(mocks.regenerate).not.toHaveBeenCalled();
  });

  it("klik na „Podobne projekty” rozwija sekcję POD ramą (nie nad rankingiem)", async () => {
    renderHub();

    expect(screen.queryByTestId("historical-mock")).not.toBeInTheDocument();

    await userEvent.click(await screen.findByTestId("sourcing-similar-projects-card"));
    expect(await screen.findByTestId("historical-mock")).toBeInTheDocument();

    // Drugi klik zwija z powrotem.
    await userEvent.click(screen.getByTestId("sourcing-similar-projects-card"));
    await waitFor(() =>
      expect(screen.queryByTestId("historical-mock")).not.toBeInTheDocument(),
    );
  });

  it("„Odśwież propozycje” woła proposalsApi.regenerate i odświeża ai-matches", async () => {
    renderHub();

    await userEvent.click(
      await screen.findByRole("button", { name: "Odśwież propozycje" }),
    );

    await waitFor(() => expect(mocks.regenerate).toHaveBeenCalledWith(7));
    await waitFor(() => expect(mocks.showSuccess).toHaveBeenCalled());
    // Regeneracja refetchuje ranking — drugie wywołanie ai-matches.
    await waitFor(() => expect(mocks.getMatches.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("readOnly ukrywa „Odśwież propozycje”, ale liczniki i nawigacja zostają", async () => {
    const { onTabChange } = renderHub({ readOnly: true });

    expect(await screen.findByTestId("sourcing-ai-matching-card")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Odśwież propozycje" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByTestId("sourcing-manual-search-card"));
    expect(onTabChange).toHaveBeenCalledWith("manual-search");
  });

  it("stan awarii: ai-matches padnięte pokazuje „—” zamiast liczb, reszta huba działa dalej", async () => {
    mocks.getMatches.mockRejectedValue(new Error("500"));

    renderHub();

    const card = await screen.findByTestId("sourcing-ai-matching-card");
    await waitFor(() => expect(mocks.getMatches).toHaveBeenCalled());

    await waitFor(() => {
      expect(within(card).getAllByText("—").length).toBeGreaterThanOrEqual(2);
    });
    // Shortlista ma OSOBNE zapytanie — awaria ai-matches jej nie zabiera.
    expect(within(card).getByText("0")).toBeInTheDocument();

    // Reszta huba (inne karty, C2, historia) nadal renderuje się normalnie —
    // jedna padnięta liczba nie może zawiesić/schować całej ramy.
    expect(screen.getByTestId("sourcing-manual-search-card")).toBeInTheDocument();
    expect(screen.getByTestId("sourcing-portals-card")).toBeInTheDocument();
    expect(screen.getByTestId("c2-mock")).toBeInTheDocument();
  });
});
