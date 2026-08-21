import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  selectMatchesForHistory,
  SuggestedCandidatesWidget,
} from "@/components/SuggestedCandidatesWidget";
import type { CandidateMatch, RecommendationMeta, ScoreBreakdown } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  latest: vi.fn(),
  regenerate: vi.fn(),
  forJob: vi.fn(),
  assignToJob: vi.fn(),
  logHistory: vi.fn(),
  shortlistAdd: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  proposalsApi: {
    latest: (...args: unknown[]) => mocks.latest(...args),
    regenerate: (...args: unknown[]) => mocks.regenerate(...args),
  },
  recommendationsApi: {
    forJob: (...args: unknown[]) => mocks.forJob(...args),
    assignToJob: (...args: unknown[]) => mocks.assignToJob(...args),
  },
  matchHistoryApi: {
    log: (...args: unknown[]) => mocks.logHistory(...args),
  },
}));

vi.mock("@/lib/candidate-search-api", () => ({
  shortlistApi: {
    add: (...args: unknown[]) => mocks.shortlistAdd(...args),
  },
}));

vi.mock("@/components/v2/filters/LocationInput", () => ({
  LocationInput: () => <input aria-label="Lokalizacja" />,
}));

vi.mock("@/components/v2/pages/candidate-list-helpers", () => ({
  formatCandidateLocation: (value: string | null) => value,
}));

const BREAKDOWN: ScoreBreakdown = {
  candidate_id: 42,
  job_id: 7,
  total: 82,
  semantic: { points: 35, max: 40, reason: "high similarity" },
  skills: { points: 25, max: 30, reason: "must skills" },
  salary: { points: 10, max: 15, reason: "in range" },
  location: { points: 8, max: 10, reason: "same city" },
  availability: { points: 4, max: 5, reason: "available" },
  matching_must: ["Python"],
  gap_must: [],
  matching_nice: [],
  gap_nice: [],
  penalties: [],
};

function candidateMatch(
  totalScore: number | null,
  breakdown: ScoreBreakdown | null = null,
): CandidateMatch {
  return {
    candidate: {
      id: 42,
      name: "Anna",
      lastname: "Nowak",
      email: null,
      location: "Warszawa",
      champion: false,
      years_it_experience: 6,
      competence_category: "Backend",
    },
    total_score: totalScore,
    breakdown,
  };
}

function renderWidget(props: { jobHasBudget?: boolean } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SuggestedCandidatesWidget jobId={7} {...props} />
    </QueryClientProvider>,
  );
}

/** Gotowy snapshot; `extra` pozwala dołożyć (albo pominąć) `hidden`. */
function readySnapshot(extra: Record<string, unknown> = {}) {
  return {
    data: {
      id: 3,
      job_id: 7,
      status: "ready",
      source: "create",
      top_k: 20,
      profile_id: 0,
      created_at: "2026-08-19T00:00:00Z",
      error_message: null,
      degraded: false,
      stale: false,
      run_id: null,
      candidates: [candidateMatch(70, BREAKDOWN)],
      ...extra,
    },
  };
}

/** Odpowiedź żywego /recommendations z jawnym zestawem liczników ukrytych. */
function liveResponse(
  matches: CandidateMatch[],
  hidden?: { over_budget: number; remote_only: number },
) {
  return {
    data: {
      job_id: 7,
      job_title: "Backend Developer",
      search_type: "hybrid",
      matches,
      meta: { mode: "dense", degraded: false, reason: null, hidden },
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.latest.mockRejectedValue({ response: { status: 404 } });
  mocks.regenerate.mockResolvedValue({ data: {} });
  mocks.assignToJob.mockResolvedValue({ data: {} });
  mocks.shortlistAdd.mockResolvedValue({
    added: [42],
    skipped: [],
    total_added: 1,
    total_skipped: 0,
  });
});

describe("SuggestedCandidatesWidget degraded recommendations", () => {
  it("renders BM25 explicitly without formatting null as a numeric score", async () => {
    mocks.forJob.mockResolvedValue({
      data: {
        job_id: 7,
        job_title: "Backend Developer",
        search_type: "hybrid",
        matches: [candidateMatch(null)],
        meta: {
          mode: "bm25",
          degraded: true,
          reason: "semantic_unavailable",
        },
      },
    });

    renderWidget();
    fireEvent.click(await screen.findByTestId("suggest-candidates-btn"));

    expect(await screen.findByTestId("degraded-recommendations-notice")).toHaveTextContent(
      "trybie awaryjnym BM25",
    );
    expect(screen.getByTestId("degraded-score-42")).toHaveTextContent(
      "BM25 · tryb awaryjny",
    );
    expect(screen.queryByText("0/100")).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.logHistory).not.toHaveBeenCalled());
  });

  it("flags a degraded snapshot ranking as a fallback", async () => {
    mocks.latest.mockResolvedValue({
      data: {
        id: 1,
        job_id: 7,
        status: "ready",
        source: "create",
        top_k: 20,
        profile_id: 0,
        created_at: "2026-08-04T00:00:00Z",
        error_message: null,
        degraded: true,
        candidates: [candidateMatch(70, BREAKDOWN)],
      },
    });

    renderWidget();

    expect(
      await screen.findByTestId("degraded-recommendations-notice"),
    ).toBeInTheDocument();
  });

  it("prompts a re-run when the snapshot is stale", async () => {
    mocks.latest.mockResolvedValue({
      data: {
        id: 2,
        job_id: 7,
        status: "ready",
        source: "handoff",
        top_k: 20,
        profile_id: 0,
        created_at: "2026-08-04T00:00:00Z",
        error_message: null,
        degraded: false,
        stale: true,
        run_id: "r1",
        candidates: [candidateMatch(70, BREAKDOWN)],
      },
    });

    renderWidget();

    expect(
      await screen.findByTestId("stale-ranking-notice"),
    ).toBeInTheDocument();
  });

  it("primary action adds the candidate to the shortlist, not the pipeline", async () => {
    mocks.forJob.mockResolvedValue({
      data: {
        job_id: 7,
        job_title: "Backend Developer",
        search_type: "hybrid",
        matches: [candidateMatch(82, BREAKDOWN)],
        meta: { mode: "dense", degraded: false, reason: null },
      },
    });

    renderWidget();
    fireEvent.click(await screen.findByTestId("suggest-candidates-btn"));

    fireEvent.click(await screen.findByText("Do shortlisty"));

    await waitFor(() => expect(mocks.shortlistAdd).toHaveBeenCalledWith(7, [42]));
    // The default action stages for evaluation — it must NOT open the pipeline.
    expect(mocks.assignToJob).not.toHaveBeenCalled();
    expect(await screen.findByText("✓ Na shortliście")).toBeInTheDocument();
  });

  it("filters unscored and explicitly degraded results out of match history", () => {
    const normalMeta: RecommendationMeta = {
      mode: "dense",
      degraded: false,
      reason: null,
    };
    const degradedMeta: RecommendationMeta = {
      mode: "bm25",
      degraded: true,
      reason: "semantic_unavailable",
    };
    const scored = candidateMatch(82, BREAKDOWN);
    const unscored = candidateMatch(null);

    expect(selectMatchesForHistory([unscored, scored], normalMeta)).toEqual([scored]);
    expect(selectMatchesForHistory([scored], degradedMeta)).toEqual([]);
  });
});
/**
 * Trzy komunikaty, które kłamały: pusty wynik oskarżał filtry także wtedy, gdy
 * nic nie ukryły, komunikaty „lokalizacji" pokazywały puste cudzysłowy przy
 * trybie samych przełączników, a etykieta sufitu budżetu obiecywała filtr nad
 * snapshotem sprzed migracji 0237, który nigdy przez ten filtr nie przeszedł.
 */
describe("SuggestedCandidatesWidget — przełączniki mówią prawdę", () => {
  it("pusty wynik przy zerowych licznikach NIE oskarża filtrów wykluczających", async () => {
    mocks.forJob.mockResolvedValue(
      liveResponse([], { over_budget: 0, remote_only: 0 }),
    );

    renderWidget();
    fireEvent.click(screen.getByTestId("switch-remote-only"));

    const notice = await screen.findByTestId("switches-no-results");
    expect(notice).toHaveTextContent("Nie znaleziono pasujących kandydatów");
    expect(notice.textContent).not.toMatch(/ukryci przez włączone filtry/);
    // Margines budżetu zniknął z UI wraz z #1207 (sufit jest twardy) —
    // odesłanie do niego wysyłało rekrutera po nieistniejący suwak.
    expect(notice.textContent).not.toMatch(/margines/i);
  });

  it("oskarża przełączniki dopiero wtedy, gdy liczniki mówią, że kogoś ukryły", async () => {
    mocks.forJob.mockResolvedValue(
      liveResponse([], { over_budget: 3, remote_only: 0 }),
    );

    renderWidget();
    fireEvent.click(screen.getByTestId("switch-remote-only"));

    const notice = await screen.findByTestId("switches-no-results");
    expect(notice).toHaveTextContent("ukryci przez włączone filtry");
    expect(notice.textContent).not.toMatch(/margines/i);
  });

  it("komunikat ładowania nie pokazuje pustych cudzysłowów bez filtra lokalizacji", async () => {
    mocks.forJob.mockReturnValue(new Promise(() => {}));

    renderWidget();
    fireEvent.click(screen.getByTestId("switch-remote-only"));

    const loading = await screen.findByTestId("filtered-loading");
    expect(loading).toHaveTextContent("Szukam kandydatów");
    expect(loading.textContent).not.toContain("„”");
  });

  it("błąd bez filtra lokalizacji nie odsyła do filtra i daje ponowienie", async () => {
    mocks.forJob.mockRejectedValue(new Error("boom"));

    renderWidget();
    fireEvent.click(screen.getByTestId("switch-remote-only"));

    const notice = await screen.findByTestId("filtered-error");
    expect(notice.textContent).not.toMatch(/Zmień filtr/);
    await waitFor(() => expect(mocks.forJob).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId("filtered-retry"));
    await waitFor(() => expect(mocks.forJob).toHaveBeenCalledTimes(2));
  });

  it("nie obiecuje sufitu budżetu nad snapshotem sprzed 0237", async () => {
    mocks.latest.mockResolvedValue(readySnapshot());

    renderWidget();
    await screen.findByText("Anna Nowak");

    const button = screen.getByTestId("switch-over-budget");
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("Budżet oferty: ranking sprzed filtra");
    expect(
      screen.getByTestId("legacy-snapshot-budget-notice"),
    ).toHaveTextContent("Odśwież propozycje");
  });

  it("snapshot po 0237 zachowuje etykietę działającego sufitu", async () => {
    mocks.latest.mockResolvedValue(
      readySnapshot({ hidden: { over_budget: 0, remote_only: 0 } }),
    );

    renderWidget();
    await screen.findByText("Anna Nowak");

    const button = screen.getByTestId("switch-over-budget");
    expect(button).not.toBeDisabled();
    expect(button).toHaveTextContent("Poza budżetem: ukryci");
    expect(
      screen.queryByTestId("legacy-snapshot-budget-notice"),
    ).not.toBeInTheDocument();
  });
});
