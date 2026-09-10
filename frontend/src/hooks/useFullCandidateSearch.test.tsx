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

function Wrapper({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  // Queued *Once values and defaults must not leak between tests.
  vi.mocked(candidateSearchApi.start).mockReset();
  vi.mocked(candidateSearchApi.page).mockReset();
  localStorage.clear(); sessionStorage.clear();
});

test("starts only explicitly, prevents duplicate clicks and ignores a cleared request", async () => {
  let resolve!: (value: CandidateSearchStarted) => void;
  vi.mocked(candidateSearchApi.start).mockReturnValue(new Promise(done => { resolve = done; }));
  const { result } = renderHook(() => useFullCandidateSearch(), { wrapper: Wrapper });
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
  const { result } = renderHook(() => useFullCandidateSearch({ includeCandidateDetails: true }), { wrapper: Wrapper });
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
  const { result, rerender } = renderHook(({ skill }) => useFullCandidateSearch({ filters: { skill } }), { wrapper: Wrapper, initialProps: { skill: "" } });
  await act(async () => { await result.current.start({ job_id: 42 }); });
  await waitFor(() => expect(result.current.data?.state).toBe("complete"));
  act(() => result.current.setOffset(20));
  await waitFor(() => expect(candidateSearchApi.page).toHaveBeenLastCalledWith("filtered", expect.objectContaining({ offset: 20 }), expect.any(AbortSignal)));
  rerender({ skill: "python" });
  await waitFor(() => expect(candidateSearchApi.page).toHaveBeenLastCalledWith("filtered", expect.objectContaining({ skill: "python", offset: 0 }), expect.any(AbortSignal)));
  expect(candidateSearchApi.start).toHaveBeenCalledTimes(1);
});

test("saved request restores the shared run instead of an older tab-local snapshot", async () => {
  const key = "nexus-full-job:7:42";
  sessionStorage.setItem(key, "old-radar-run");
  localStorage.setItem(key, "new-pipeline-run");
  const { result } = renderHook(() => useFullCandidateSearch({ storageKey: key, shareAcrossTabs: true }), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.runId).toBe("new-pipeline-run"));
  expect(sessionStorage.getItem(key)).toBeNull();
  expect(candidateSearchApi.start).not.toHaveBeenCalled();
});

test("another tab replaces the run and resets pagination without starting AI; other actors are ignored", async () => {
  const key = "nexus-full-job:7:42";
  localStorage.setItem(key, "first");
  const { result } = renderHook(() => useFullCandidateSearch({ storageKey: key, shareAcrossTabs: true }), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.runId).toBe("first"));
  act(() => result.current.setOffset(20));
  act(() => {
    localStorage.setItem(key, "second");
    window.dispatchEvent(new StorageEvent("storage", { key, newValue: "second", storageArea: localStorage }));
  });
  await waitFor(() => expect(result.current.runId).toBe("second"));
  expect(result.current.offset).toBe(0);
  act(() => window.dispatchEvent(new StorageEvent("storage", { key: "nexus-full-job:8:42", newValue: "other-user", storageArea: localStorage })));
  expect(result.current.runId).toBe("second");
  act(() => {
    localStorage.removeItem(key);
    window.dispatchEvent(new StorageEvent("storage", { key, newValue: null, storageArea: localStorage }));
  });
  await waitFor(() => expect(result.current.runId).toBeNull());
  expect(candidateSearchApi.start).not.toHaveBeenCalled();
});

test("two consumers in the same document share an explicitly started run", async () => {
  vi.mocked(candidateSearchApi.start).mockResolvedValue({ run_id: "shared", state: "queued", population: 60, brief_status: "provided", versions: {} });
  const options = { storageKey: "nexus-full-job:7:42", shareAcrossTabs: true };
  const a = renderHook(() => useFullCandidateSearch(options), { wrapper: Wrapper });
  const b = renderHook(() => useFullCandidateSearch(options), { wrapper: Wrapper });
  await act(async () => { await a.result.current.start({ job_id: 42 }); });
  await waitFor(() => expect(b.result.current.runId).toBe("shared"));
  expect(a.result.current.runId).toBe("shared");
  expect(candidateSearchApi.start).toHaveBeenCalledTimes(1);
});

const runningPage = {
  run_id: "stale", state: "running" as const, versions: {}, results: [],
  counts: { population: 10, pending: 5, evaluated: 5, failed: 0, eligible: 5, excluded: 0, needs_verification: 0 },
};

test("a failed read stops polling; a stale (409) run is offered as a new run, not a retry", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const conflict = Object.assign(new Error("Request zmienił się"), { response: { status: 409 } });
    vi.mocked(candidateSearchApi.start).mockResolvedValue({ run_id: "stale", state: "queued", population: 10, brief_status: "provided", versions: {} });
    vi.mocked(candidateSearchApi.page).mockResolvedValueOnce(runningPage).mockRejectedValue(conflict);
    const { result } = renderHook(() => useFullCandidateSearch(), { wrapper: Wrapper });
    await act(async () => { await result.current.start({ job_id: 42 }); });
    await waitFor(() => expect(result.current.data?.state).toBe("running"));
    expect(result.current.needsNewRun).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    await waitFor(() => expect(result.current.error).toBe(conflict));
    const reads = vi.mocked(candidateSearchApi.page).mock.calls.length;
    // TanStack keeps the last "running" data after an error; polling on it
    // would repeat the 409 every 1.5 s forever.
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(vi.mocked(candidateSearchApi.page).mock.calls.length).toBe(reads);
    expect(result.current.running).toBe(false);
    expect(result.current.needsNewRun).toBe(true);
    expect(candidateSearchApi.start).toHaveBeenCalledTimes(1);
  } finally {
    vi.useRealTimers();
  }
});

test("a transient read error during a running scan keeps polling and keeps the start locked", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const outage = Object.assign(new Error("Bad gateway"), { response: { status: 502 } });
    vi.mocked(candidateSearchApi.start).mockResolvedValue({ run_id: "live", state: "queued", population: 10, brief_status: "provided", versions: {} });
    vi.mocked(candidateSearchApi.page)
      .mockResolvedValueOnce(runningPage)
      .mockRejectedValueOnce(outage)
      .mockResolvedValue({ ...runningPage, state: "complete" });
    const { result } = renderHook(() => useFullCandidateSearch(), { wrapper: Wrapper });
    await act(async () => { await result.current.start({ job_id: 42 }); });
    await waitFor(() => expect(result.current.data?.state).toBe("running"));
    await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    await waitFor(() => expect(result.current.error).toBe(outage));
    // A deploy or a network blip is not the end of the scan: the start button
    // stays locked (no duplicate 3-minute scan) and polling resumes by itself.
    expect(result.current.running).toBe(true);
    expect(result.current.needsNewRun).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(5_500); });
    await waitFor(() => expect(result.current.data?.state).toBe("complete"));
    expect(candidateSearchApi.start).toHaveBeenCalledTimes(1);
  } finally {
    vi.useRealTimers();
  }
});

test("a failed run is terminal: no polling, no spinner, replacement offered", async () => {
  vi.mocked(candidateSearchApi.start).mockResolvedValue({ run_id: "broken", state: "queued", population: 10, brief_status: "provided", versions: {} });
  vi.mocked(candidateSearchApi.page).mockResolvedValue({ ...runningPage, run_id: "broken", state: "failed", error_code: "stalled" });
  const { result } = renderHook(() => useFullCandidateSearch(), { wrapper: Wrapper });
  await act(async () => { await result.current.start({ job_id: 42 }); });
  await waitFor(() => expect(result.current.data?.state).toBe("failed"));
  expect(result.current.running).toBe(false);
  expect(result.current.needsNewRun).toBe(true);
  expect(result.current.error).toBeNull();
});

test("a transient read error is retried by re-reading the same run", async () => {
  const outage = Object.assign(new Error("Sieć niedostępna"), { response: { status: 503 } });
  vi.mocked(candidateSearchApi.start).mockResolvedValue({ run_id: "same", state: "queued", population: 10, brief_status: "provided", versions: {} });
  vi.mocked(candidateSearchApi.page).mockRejectedValueOnce(outage).mockResolvedValue({ ...runningPage, run_id: "same", state: "complete" });
  const { result } = renderHook(() => useFullCandidateSearch(), { wrapper: Wrapper });
  await act(async () => { await result.current.start({ job_id: 42 }); });
  await waitFor(() => expect(result.current.error).toBe(outage));
  expect(result.current.needsNewRun).toBe(false);
  await act(async () => { await result.current.refresh(); });
  await waitFor(() => expect(result.current.data?.state).toBe("complete"));
  expect(candidateSearchApi.start).toHaveBeenCalledTimes(1);
});

test("a late start response cannot replace a newer shared run from another tab", async () => {
  let resolve!: (value: CandidateSearchStarted) => void;
  vi.mocked(candidateSearchApi.start).mockReturnValue(new Promise(done => { resolve = done; }));
  const key = "nexus-full-job:7:42";
  const { result } = renderHook(() => useFullCandidateSearch({ storageKey: key, shareAcrossTabs: true }), { wrapper: Wrapper });
  let pending!: ReturnType<typeof result.current.start>;
  act(() => { pending = result.current.start({ job_id: 42 }); });
  act(() => {
    localStorage.setItem(key, "newer-run");
    window.dispatchEvent(new StorageEvent("storage", { key, storageArea: localStorage }));
  });
  await act(async () => {
    resolve({ run_id: "late-old-run", state: "queued", population: 60, brief_status: "provided", versions: {} });
    await pending;
  });
  expect(result.current.runId).toBe("newer-run");
  expect(localStorage.getItem(key)).toBe("newer-run");
});
