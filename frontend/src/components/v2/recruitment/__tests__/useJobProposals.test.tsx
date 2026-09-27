import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CandidateSearchPage } from "@/lib/full-candidate-search-api";
import type { ProposalInboxItem, ProposalInboxPage } from "@/lib/job-proposals-api";
import { DEFAULT_PROPOSAL_FILTERS } from "@/lib/proposals-merge";

const mocks = vi.hoisted(() => ({
  add: vi.fn(),
  shortlistAdd: vi.fn(),
  inbox: vi.fn(),
  dismiss: vi.fn(),
  restore: vi.fn(),
  latestRun: vi.fn(),
  similar: vi.fn(),
  latestSnapshot: vi.fn(),
  regenerate: vi.fn(),
  pipelineScores: vi.fn(),
  toast: { showSuccess: vi.fn(), showError: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() },
  fullSearch: { current: {} as Record<string, unknown> },
}));

vi.mock("@/lib/candidate-search-api", () => ({
  proposalsBulkApi: { add: (...a: unknown[]) => mocks.add(...a) },
  shortlistApi: { add: (...a: unknown[]) => mocks.shortlistAdd(...a) },
}));
vi.mock("@/lib/job-proposals-api", async (orig) => ({
  ...(await orig<typeof import("@/lib/job-proposals-api")>()),
  jobProposalsApi: {
    inbox: (...a: unknown[]) => mocks.inbox(...a),
    dismiss: (...a: unknown[]) => mocks.dismiss(...a),
    restore: (...a: unknown[]) => mocks.restore(...a),
    latestRun: (...a: unknown[]) => mocks.latestRun(...a),
  },
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  historicalCandidatesApi: { forJob: (...a: unknown[]) => mocks.similar(...a) },
  proposalsApi: { latest: (...a: unknown[]) => mocks.latestSnapshot(...a), regenerate: (...a: unknown[]) => mocks.regenerate(...a) },
  matchingApi: { pipelineScores: (...a: unknown[]) => mocks.pipelineScores(...a) },
}));
vi.mock("@/hooks/useFullCandidateSearch", () => ({ useFullCandidateSearch: () => mocks.fullSearch.current }));
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));
vi.mock("@/components/v2/jobs/JobShortlist", () => ({ jobShortlistQueryKey: (id: number) => ["job-shortlist", id] }));
vi.mock("@/store/auth", () => ({ useAuthStore: (sel: (s: unknown) => unknown) => sel({ user: { id: 9 } }) }));

import { groupAddsByOrigin, useJobProposals } from "@/components/v2/recruitment/useJobProposals";

const JOB = 42;

function inboxItem(id: number): ProposalInboxItem {
  return {
    candidate: { id, name: "Jan", lastname: `Inbox${id}`, title: null, city: null, availability_status: null, availability_date: null, expected_rate_hourly: null, expected_rate_redacted: false },
    sources: ["new_cv"], score: 60, evidence: null, first_seen_at: null, last_seen_at: null, is_new: false, status: "proposed", eligibility: null,
  };
}
const inboxPage = (ids: number[]): ProposalInboxPage => ({ job_id: JOB, status: "proposed", items: ids.map(inboxItem), total: ids.length, hidden_on_page: 0, limit: 50, offset: 0, next_offset: null });

function runPage(ids: number[]): CandidateSearchPage {
  return {
    run_id: "run-7", state: "complete",
    counts: { population: 10, pending: 0, failed: 0, evaluated: 10, eligible: ids.length, excluded: 0, needs_verification: 0 },
    results: ids.map((id) => ({
      candidate: { id, name: "Ewa", lastname: `Run${id}`, location: null, competence_category: null, years_it_experience: null, availability_status: null, champion: false, avatar_url: null },
      match: null, fit_score: 80, measurement: "measured" as const, requirements: [], eligibility: null,
    })),
    versions: {}, ranking_complete: true, coverage_complete: true,
  };
}

function idleSearch(data?: CandidateSearchPage) {
  return { start: vi.fn(), clear: vi.fn(), adopt: vi.fn(), refresh: vi.fn(), runId: data ? data.run_id : null, offset: 0, setOffset: vi.fn(), setMinScore: vi.fn(), minScore: 0, data, error: null, starting: false, running: false, loading: false, fetching: false, needsNewRun: false };
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const hook = renderHook(() => useJobProposals(JOB, { filters: DEFAULT_PROPOSAL_FILTERS, budgetHourly: null, pipelineCandidateIds: [] }), { wrapper });
  return { ...hook, invalidate, client };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.fullSearch.current = idleSearch(runPage([1]));
  mocks.inbox.mockResolvedValue(inboxPage([2, 3]));
  mocks.latestRun.mockResolvedValue({ job_id: JOB, run: null });
  mocks.similar.mockResolvedValue({ data: { job_id: JOB, tier_used: "primary", similar_jobs: [], meta: { tier_a_count: 0, tier_b_count: 0, total_sources: 0, reason_if_empty: null }, candidates: [{ candidate_id: 4, name: "Ola", lastname: "Hist", avatar_url: null, competence_category: null, historical_score: 3, tier: "A", negative_signal: false, recommended_count: 0, sources: [], current_availability: "unknown", current_status: null, same_client: false, rejected_by_same_client: false }] } });
  mocks.latestSnapshot.mockRejectedValue({ response: { status: 404 } });
  mocks.add.mockImplementation(async (_job: number, body: { candidate_ids: number[] }) => ({ added: body.candidate_ids, skipped: [], warnings: [], total_added: body.candidate_ids.length, total_skipped: 0 }));
  mocks.dismiss.mockResolvedValue({ job_id: JOB, candidate_id: 2, dismissed: true });
});

describe("useJobProposals", () => {
  it("scala skrzynkę, żywy przegląd i podobne projekty w jedną listę", async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.rows.map((r) => r.candidateId).sort()).toEqual([1, 2, 3, 4]));
    expect(result.current.sourceCounts).toMatchObject({ all: 4, full_base: 1, new_cv: 2, similar_projects: 1 });
  });

  it("przekazanie od praktykanta (0374) przechodzi do wiersza: źródło, powód i notatka", async () => {
    mocks.inbox.mockResolvedValue({
      ...inboxPage([]),
      items: [
        {
          ...inboxItem(8),
          sources: ["trainee"],
          trainee_handover: { by_name: "Ola Kamińska", note: "Szuka od listopada.", at: "2026-09-24T09:00:00Z" },
        },
      ],
      total: 1,
    });
    const { result } = setup();
    await waitFor(() => expect(result.current.rows.some((r) => r.candidateId === 8)).toBe(true));
    const row = result.current.rows.find((r) => r.candidateId === 8)!;
    expect(row.sources).toEqual(["trainee"]);
    expect(row.reason).toBe("Od praktykanta: Ola Kamińska · 24.09");
    expect(row.handoverNote).toBe("Szuka od listopada.");
    expect(result.current.sourceCounts).toMatchObject({ trainee: 1 });
  });

  it("dodanie wysyła source/run_id wg pochodzenia wiersza i unieważnia kanban (oba klucze), propozycje i listę rekrutacji", async () => {
    const { result, invalidate } = setup();
    await waitFor(() => expect(result.current.rows).toHaveLength(4));
    act(() => result.current.addToJob([1, 2, 4], { note: "z propozycji" }));
    await waitFor(() => expect(mocks.add).toHaveBeenCalledTimes(3));
    expect(mocks.add).toHaveBeenCalledWith(JOB, { candidate_ids: [1], note: "z propozycji", source: "full_search", run_id: "run-7" });
    expect(mocks.add).toHaveBeenCalledWith(JOB, { candidate_ids: [4], note: "z propozycji", source: "historical" });
    // Skrzynka ma własne źródło; `run_id` tylko wtedy, gdy serwer go podał.
    expect(mocks.add).toHaveBeenCalledWith(JOB, { candidate_ids: [2], note: "z propozycji", source: "proposal_inbox" });
    await waitFor(() => expect(result.current.rows.map((r) => r.candidateId)).toEqual([3]));
    const keys = invalidate.mock.calls.map(([arg]) => JSON.stringify((arg as { queryKey: unknown }).queryKey));
    for (const key of [["kanban", "42"], ["kanban", 42], ["pipeline-scores"], ["job-proposals", 42], ["jobs"], ["jobs-v2"]]) {
      expect(keys).toContain(JSON.stringify(key));
    }
  });

  it("konflikt z klientem wraca jako ostrzeżenie w komunikacie, nie jako pominięcie", async () => {
    mocks.add.mockResolvedValue({ added: [2], skipped: [], warnings: [{ candidate_id: 2, reason: "client_nda" }], total_added: 1, total_skipped: 0 });
    const { result } = setup();
    await waitFor(() => expect(result.current.rows).toHaveLength(4));
    act(() => result.current.addToJob([2]));
    await waitFor(() => expect(mocks.toast.showToast).toHaveBeenCalled());
    expect(mocks.toast.showToast).toHaveBeenCalledWith("Dodano do rekrutacji: 1 — uwaga: 1× konflikt: NDA z klientem", "success");
  });

  it("Pomiń usuwa wiersz optymistycznie i woła API dla KAŻDEJ osoby, ze źródłem wiersza", async () => {
    let release!: () => void;
    mocks.dismiss.mockReturnValue(new Promise((resolve) => { release = () => resolve({}); }));
    const { result } = setup();
    await waitFor(() => expect(result.current.rows).toHaveLength(4));
    act(() => result.current.dismiss([2]));
    await waitFor(() => expect(result.current.rows.map((r) => r.candidateId).sort()).toEqual([1, 3, 4]));
    expect(mocks.dismiss).toHaveBeenCalledWith(JOB, 2, "new_cv");
    await act(async () => release());
  });

  it("Pomiń osoby spoza skrzynki jest trwałe, a „Cofnij” przywraca ją przez API", async () => {
    mocks.dismiss.mockResolvedValue({ dismissed: true });
    mocks.restore.mockResolvedValue({ restored: true });
    const { result } = setup();
    await waitFor(() => expect(result.current.rows).toHaveLength(4));
    act(() => result.current.dismiss([1, 4]));
    await waitFor(() => expect(mocks.toast.showActionToast).toHaveBeenCalled());
    expect(mocks.dismiss).toHaveBeenCalledWith(JOB, 1, "full_base");
    expect(mocks.dismiss).toHaveBeenCalledWith(JOB, 4, "similar_projects");
    const [, options] = mocks.toast.showActionToast.mock.calls[0];
    expect(options.actionLabel).toBe("Cofnij");
    await act(async () => { await options.onAction(); });
    await waitFor(() => expect(mocks.restore).toHaveBeenCalledTimes(2));
    expect(mocks.restore).toHaveBeenCalledWith(JOB, 1);
    await waitFor(() => expect(result.current.rows.map((r) => r.candidateId)).toContain(1));
  });

  it("409 przy Pomiń (osoba właśnie trafiła do rekrutacji) nie jest błędem", async () => {
    mocks.dismiss.mockRejectedValue({ response: { status: 409, data: { detail: "Ta osoba jest już w tej rekrutacji" } } });
    const { result } = setup();
    await waitFor(() => expect(result.current.rows).toHaveLength(4));
    act(() => result.current.dismiss([2]));
    await waitFor(() => expect(mocks.toast.showSuccess).toHaveBeenCalled());
    expect(mocks.toast.showError).not.toHaveBeenCalled();
    expect(mocks.toast.showActionToast).not.toHaveBeenCalled();
  });

  it("nieudane Pomiń przywraca wiersz i pokazuje błąd", async () => {
    mocks.dismiss.mockRejectedValue({ response: { status: 403, data: { detail: "Brak członkostwa w zespole rekrutacji" } } });
    // Po błędzie skrzynka jest czytana ponownie — osoba nadal w niej jest.
    const { result } = setup();
    await waitFor(() => expect(result.current.rows).toHaveLength(4));
    act(() => result.current.dismiss([2]));
    await waitFor(() => expect(mocks.toast.showError).toHaveBeenCalledWith("Brak członkostwa w zespole rekrutacji"));
    await waitFor(() => expect(result.current.rows.map((r) => r.candidateId)).toContain(2));
  });

  it("przeglądarka nie zna przeglądu → podpina ostatni zakończony z serwera", async () => {
    const search = idleSearch();
    mocks.fullSearch.current = search;
    mocks.latestRun.mockResolvedValue({
      job_id: JOB,
      run: { run_id: "run-srv", state: "partial", completed_at: "2026-09-21T18:39:00Z", origin: "manual", own: true },
    });
    setup();
    await waitFor(() => expect(search.adopt).toHaveBeenCalledWith("run-srv"));
  });

  it("znany przegląd nie jest podmieniany ostatnim z serwera", async () => {
    mocks.latestRun.mockResolvedValue({
      job_id: JOB,
      run: { run_id: "run-srv", state: "complete", completed_at: null, origin: "auto", own: false },
    });
    const { result } = setup();
    await waitFor(() => expect(result.current.rows.length).toBeGreaterThan(0));
    expect((mocks.fullSearch.current as { adopt: ReturnType<typeof vi.fn> }).adopt).not.toHaveBeenCalled();
  });

  it("przegląd w toku albo przerwany nie wnosi wierszy", async () => {
    mocks.fullSearch.current = idleSearch({ ...runPage([1]), state: "failed" });
    const { result } = setup();
    await waitFor(() => expect(result.current.rows).toHaveLength(3));
    expect(result.current.rows.map((r) => r.candidateId)).not.toContain(1);
  });

  it("nic zmierzonego na stronie przeglądu = awaria silnika", async () => {
    const page = runPage([1]);
    page.results[0] = { ...page.results[0], fit_score: null, measurement: "unavailable" };
    mocks.fullSearch.current = idleSearch(page);
    const { result } = setup();
    await waitFor(() => expect(result.current.status.engineDegraded).toBe(true));
  });

  it("zdegradowana MIGAWKA rekomendacji nie zapala banera awarii silnika", async () => {
    mocks.latestSnapshot.mockResolvedValue({ data: { status: "ready", degraded: true, stale: false, candidates: [] } });
    const { result } = setup();
    await waitFor(() => expect(result.current.status.recommendations.degraded).toBe(true));
    expect(result.current.status.engineDegraded).toBe(false);
  });
});

describe("groupAddsByOrigin", () => {
  it("grupuje po (source, run_id): żywy przegląd → skrzynka → podobne → rekomendacje", () => {
    const entry = (id: number, runId: string | null, origins: string[]) => ({ row: { candidateId: id, runId }, detail: { origins } }) as never;
    expect(
      groupAddsByOrigin([
        entry(1, "a", ["run"]),
        entry(2, "a", ["run", "inbox"]),
        entry(3, null, ["similar"]),
        entry(4, null, ["recommendation"]),
        entry(5, "auto-9", ["inbox"]),
        entry(6, null, ["inbox", "similar"]),
      ]),
    ).toEqual([
      { source: "full_search", runId: "a", ids: [1, 2] },
      { source: "historical", runId: null, ids: [3] },
      { source: "recommendation", runId: null, ids: [4] },
      { source: "proposal_inbox", runId: "auto-9", ids: [5] },
      { source: "proposal_inbox", runId: null, ids: [6] },
    ]);
  });

  it("wiersz adoptowanego przeglądu nocnego idzie jako skrzynka propozycji (R8-N11-7)", () => {
    const entry = (id: number, runId: string | null, origins: string[]) => ({ row: { candidateId: id, runId }, detail: { origins } }) as never;
    expect(
      groupAddsByOrigin([entry(1, "auto-9", ["run"]), entry(2, "manual-1", ["run"])], "auto-9"),
    ).toEqual([
      { source: "proposal_inbox", runId: "auto-9", ids: [1] },
      { source: "full_search", runId: "manual-1", ids: [2] },
    ]);
  });
});
