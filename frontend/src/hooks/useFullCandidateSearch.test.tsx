import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { vi, expect, test, beforeEach } from "vitest";
import { candidateSearchApi, type CandidateSearchStarted } from "@/lib/full-candidate-search-api";
import { useFullCandidateSearch } from "./useFullCandidateSearch";

vi.mock("@/lib/full-candidate-search-api", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/full-candidate-search-api")>(),
  candidateSearchApi: { start: vi.fn(), page: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.clearAllMocks());

test("starts only explicitly, prevents duplicate clicks and ignores a cleared request", async () => {
  let resolve!: (value: CandidateSearchStarted) => void;
  vi.mocked(candidateSearchApi.start).mockReturnValue(new Promise(done => { resolve = done; }));
  const { result } = renderHook(() => useFullCandidateSearch(), { wrapper });
  expect(candidateSearchApi.start).not.toHaveBeenCalled();
  let pending!: ReturnType<typeof result.current.start>;
  act(() => {
    pending = result.current.start({ job_id: 42 });
    void result.current.start({ job_id: 42 });
  });
  expect(candidateSearchApi.start).toHaveBeenCalledTimes(1);
  act(() => result.current.clear());
  await act(async () => {
    resolve({ run_id: "old", state: "queued", population: 60000, brief_status: "provided", versions: {} });
    await pending;
  });
  expect(result.current.runId).toBeNull();
  expect(candidateSearchApi.page).not.toHaveBeenCalled();
});

test("page navigation reuses the same run without launching another scan", async () => {
  vi.mocked(candidateSearchApi.start).mockResolvedValue({ run_id: "run", state: "queued", population: 60, brief_status: "provided", versions: {} });
  vi.mocked(candidateSearchApi.page).mockResolvedValue({
    run_id: "run", state: "partial", versions: {},
    counts: { population: 60, pending: 0, evaluated: 60, failed: 0, eligible: 60, excluded: 0, needs_verification: 1 },
    results: [], next_offset: 20, total_after_threshold: 60,
  });
  const { result } = renderHook(() => useFullCandidateSearch({ includeCandidateDetails: true }), { wrapper });
  await act(async () => { await result.current.start({ job_id: 42 }); });
  await waitFor(() => expect(result.current.data?.state).toBe("partial"));
  act(() => result.current.setOffset(20));
  await waitFor(() => expect(candidateSearchApi.page).toHaveBeenLastCalledWith("run", {
    offset: 20, limit: 20, min_score: 0, include_candidate_details: true,
  }, expect.any(AbortSignal)));
  expect(candidateSearchApi.start).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(result.current.running).toBe(false));
});

test("changing a filter resets the page and reads the same run without another AI scan", async () => {
  vi.mocked(candidateSearchApi.start).mockResolvedValue({ run_id: "filtered", state: "queued", population: 100, brief_status: "provided", versions: {} });
  vi.mocked(candidateSearchApi.page).mockResolvedValue({
    run_id: "filtered", state: "complete", versions: {}, results: [],
    counts: { population: 100, pending: 0, evaluated: 100, failed: 0, eligible: 100, excluded: 0, needs_verification: 0 },
  });
  const { result, rerender } = renderHook(({ skill }) => useFullCandidateSearch({ filters: { skill } }), { wrapper, initialProps: { skill: "" } });
  await act(async () => { await result.current.start({ job_id: 42 }); });
  await waitFor(() => expect(result.current.data?.state).toBe("complete"));
  act(() => result.current.setOffset(20));
  await waitFor(() => expect(candidateSearchApi.page).toHaveBeenLastCalledWith("filtered", expect.objectContaining({ offset: 20 }), expect.any(AbortSignal)));
  rerender({ skill: "python" });
  await waitFor(() => expect(candidateSearchApi.page).toHaveBeenLastCalledWith("filtered", expect.objectContaining({ skill: "python", offset: 0 }), expect.any(AbortSignal)));
  expect(candidateSearchApi.start).toHaveBeenCalledTimes(1);
});
