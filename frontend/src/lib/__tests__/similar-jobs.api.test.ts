import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: http }));

import {
  similarJobsApi,
  similarJobsKey,
  similarPeopleKey,
  similarPeopleWithRestKey,
  similarPersonScoreKey,
  similarSearchKey,
  useLinkSimilarJobs,
  useReassignFromSimilar,
  useSimilarJobs,
  useSimilarPeople,
  useUnlinkSimilarJob,
  type SimilarJobsPayload,
} from "@/lib/similar-jobs-api";

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
  return { qc, wrapper };
}

const PAYLOAD: SimilarJobsPayload = {
  job_id: 4,
  reassigned_count: 0,
  linked: [],
  suggestions: [
    {
      id: 9,
      title: "Analityk danych",
      reference_number: "ACME/009/2026",
      status: "published",
      closed_at: null,
      client_name: "Fikcyjna Sp. z o.o.",
      similarity: 81,
      similarity_kind: "vector",
      sent_count: 2,
      linked: false,
    },
  ],
};

beforeEach(() => {
  for (const fn of Object.values(http)) fn.mockReset();
});

describe("klucze cache podobnych rekrutacji", () => {
  it("ludzie z „pozostałymi” mają osobny klucz pod wspólnym prefiksem", () => {
    expect(similarPeopleKey(4, 9)).toEqual(["similar-people", 4, 9]);
    expect(similarPeopleWithRestKey(4, 9)).toEqual(["similar-people", 4, 9, "rest"]);
    expect(similarSearchKey(4, "java")).toEqual(["similar-jobs-search", 4, "java"]);
    expect(similarPersonScoreKey(4, 31)).toEqual(["similar-person-score", 4, 31]);
  });
});

describe("similarJobsApi — adresy, parametry i rozpakowanie odpowiedzi", () => {
  it("get / link / unlink", async () => {
    http.get.mockResolvedValueOnce({ data: PAYLOAD });
    await expect(similarJobsApi.get(4)).resolves.toEqual(PAYLOAD);
    expect(http.get).toHaveBeenCalledWith("/api/jobs/4/similar");

    http.post.mockResolvedValueOnce({ data: { ...PAYLOAD, linked_now: 2, reassigned_now: 1 } });
    const linked = await similarJobsApi.link(4, [9, 11]);
    expect(linked.linked_now).toBe(2);
    expect(http.post).toHaveBeenCalledWith("/api/jobs/4/similar", { job_ids: [9, 11] });

    http.delete.mockResolvedValueOnce({ data: PAYLOAD });
    await similarJobsApi.unlink(4, 9);
    expect(http.delete).toHaveBeenCalledWith("/api/jobs/4/similar/9");
  });

  it("ludzie: lista id bez indeksów w adresie, `include_rest` tylko na żądanie", async () => {
    http.get.mockResolvedValue({ data: { job_id: 4, jobs: [] } });
    await similarJobsApi.people(4, [9, 11]);
    expect(http.get).toHaveBeenLastCalledWith("/api/jobs/4/similar/people", {
      params: { job_ids: [9, 11] },
      paramsSerializer: { indexes: null },
    });
    await similarJobsApi.people(4, [9], { includeRest: true });
    expect(http.get).toHaveBeenLastCalledWith("/api/jobs/4/similar/people", {
      params: { job_ids: [9], include_rest: true },
      paramsSerializer: { indexes: null },
    });
    await similarJobsApi.people(4, [9], { includeRest: false });
    expect(http.get.mock.calls[2][1].params).toEqual({ job_ids: [9] });
  });

  it("wyszukiwanie zwraca samą listę `items`", async () => {
    http.get.mockResolvedValueOnce({ data: { items: PAYLOAD.suggestions } });
    await expect(similarJobsApi.search(4, "analityk")).resolves.toEqual(PAYLOAD.suggestions);
    expect(http.get).toHaveBeenCalledWith("/api/jobs/4/similar/search", { params: { q: "analityk" } });
  });

  it("przepięcie wysyła rekrutacje i osoby", async () => {
    const res = { added: [31], skipped: [], total_added: 1, total_skipped: 0, linked_now: [9] };
    http.post.mockResolvedValueOnce({ data: res });
    await expect(similarJobsApi.reassign(4, [9], [31])).resolves.toEqual(res);
    expect(http.post).toHaveBeenCalledWith("/api/jobs/4/similar/reassign", { job_ids: [9], candidate_ids: [31] });
  });

  it("podgląd szkicu zwraca same sugestie", async () => {
    http.post.mockResolvedValueOnce({ data: { suggestions: PAYLOAD.suggestions } });
    const input = { title: "Analityk", must_skills: ["SQL"], client_id: null };
    await expect(similarJobsApi.preview(input)).resolves.toEqual(PAYLOAD.suggestions);
    expect(http.post).toHaveBeenCalledWith("/api/job-similarity/preview", input);
  });

  it("„Mamy championa” wysyła flagę, także `false`", async () => {
    http.post.mockResolvedValue({ data: { job_id: 4, champion_found: false, champion_found_at: null, changed: true } });
    await similarJobsApi.setChampionFound(4, false);
    expect(http.post).toHaveBeenCalledWith("/api/jobs/4/champion-found", { found: false });
  });
});

describe("useSimilarJobs", () => {
  it("pobiera podobne rekrutacje", async () => {
    const { wrapper } = setup();
    http.get.mockResolvedValueOnce({ data: PAYLOAD });
    const { result } = renderHook(() => useSimilarJobs(4), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.suggestions).toHaveLength(1);
  });

  it("nie pyta o id 0, NaN ani przy wyłączeniu", () => {
    const { wrapper } = setup();
    renderHook(() => useSimilarJobs(0), { wrapper });
    renderHook(() => useSimilarJobs(Number.NaN), { wrapper });
    renderHook(() => useSimilarJobs(4, false), { wrapper });
    expect(http.get).not.toHaveBeenCalled();
  });
});

describe("useSimilarPeople", () => {
  it("bierze ludzi pierwszej rekrutacji z odpowiedzi", async () => {
    const { wrapper } = setup();
    const people = [
      {
        candidate_id: 31,
        name: "Jan Testowy",
        furthest_stage: "client_interview",
        sent_at: "2026-10-01",
        outcome: "in_progress",
        already_in_job: false,
        selectable: true,
      },
    ];
    http.get.mockResolvedValueOnce({ data: { job_id: 4, jobs: [{ job_id: 9, people }] } });
    const { result } = renderHook(() => useSimilarPeople(4, 9), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(people);
    expect(http.get.mock.calls[0][1].params).toEqual({ job_ids: [9] });
  });

  it("pusta lista `jobs` z serwera daje pustą listę, nie błąd", async () => {
    const { wrapper } = setup();
    http.get.mockResolvedValueOnce({ data: { job_id: 4, jobs: [] } });
    const { result } = renderHook(() => useSimilarPeople(4, 9), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });

  it("nie pyta, gdy któreś id nie jest dodatnie albo zapytanie wyłączone", () => {
    const { wrapper } = setup();
    renderHook(() => useSimilarPeople(0, 9), { wrapper });
    renderHook(() => useSimilarPeople(4, 0), { wrapper });
    renderHook(() => useSimilarPeople(4, 9, false), { wrapper });
    expect(http.get).not.toHaveBeenCalled();
  });
});

describe("połączenie, rozłączenie i przepięcie odświeżają widoki", () => {
  function seed(qc: QueryClient) {
    const keys = [
      ["jobs-v2", { page: 1 }],
      ["job-proposals", 4],
      ["job-proposals", 9],
      ["similar-people", 4, 9],
      ["similar-people", 5, 9],
      ["kanban", "4"],
      ["kanban", 4],
      ["kanban", 5],
      ["pipeline-scores", 4],
    ] as const;
    for (const k of keys) qc.setQueryData(k, { seeded: true });
    return (k: readonly unknown[]) => qc.getQueryState(k)?.isInvalidated;
  }

  it("useLinkSimilarJobs: odpowiedź ląduje w cache, listy rekrutacji i skrzynki są odświeżane", async () => {
    const { qc, wrapper } = setup();
    const invalidated = seed(qc);
    const res = { ...PAYLOAD, linked_now: 1, reassigned_now: 0 };
    http.post.mockResolvedValueOnce({ data: res });
    const { result } = renderHook(() => useLinkSimilarJobs(4), { wrapper });
    await act(() => result.current.mutateAsync([9]));
    // setQueryData + invalidate: dane są, ale oznaczone do odświeżenia.
    expect(qc.getQueryData(similarJobsKey(4))).toEqual(res);
    expect(invalidated(similarJobsKey(4))).toBe(true);
    expect(invalidated(["jobs-v2", { page: 1 }])).toBe(true);
    expect(invalidated(["job-proposals", 9])).toBe(true);
    // Kanban odświeża dopiero przepięcie.
    expect(invalidated(["kanban", 4])).toBe(false);
  });

  it("useUnlinkSimilarJob: rozłącza i zapisuje odpowiedź", async () => {
    const { qc, wrapper } = setup();
    seed(qc);
    http.delete.mockResolvedValueOnce({ data: { ...PAYLOAD, suggestions: [] } });
    const { result } = renderHook(() => useUnlinkSimilarJob(4), { wrapper });
    await act(() => result.current.mutateAsync(9));
    expect(http.delete).toHaveBeenCalledWith("/api/jobs/4/similar/9");
    expect(qc.getQueryData<SimilarJobsPayload>(similarJobsKey(4))?.suggestions).toEqual([]);
  });

  it("useReassignFromSimilar: odświeża oba klucze kanbana, ludzi tej rekrutacji i oceny", async () => {
    const { qc, wrapper } = setup();
    const invalidated = seed(qc);
    http.post.mockResolvedValueOnce({
      data: { added: [31], skipped: [], total_added: 1, total_skipped: 0, linked_now: [9] },
    });
    const { result } = renderHook(() => useReassignFromSimilar(4), { wrapper });
    await act(() => result.current.mutateAsync({ jobIds: [9], candidateIds: [31] }));
    expect(http.post).toHaveBeenCalledWith("/api/jobs/4/similar/reassign", { job_ids: [9], candidate_ids: [31] });
    expect(invalidated(["kanban", "4"])).toBe(true);
    expect(invalidated(["kanban", 4])).toBe(true);
    expect(invalidated(["similar-people", 4, 9])).toBe(true);
    expect(invalidated(["pipeline-scores", 4])).toBe(true);
    expect(invalidated(["job-proposals", 4])).toBe(true);
    // Cudza rekrutacja zostaje.
    expect(invalidated(["kanban", 5])).toBe(false);
    expect(invalidated(["similar-people", 5, 9])).toBe(false);
  });

  it("useReassignFromSimilar: błąd serwera nie odświeża Tablicy", async () => {
    const { qc, wrapper } = setup();
    const invalidated = seed(qc);
    http.post.mockRejectedValueOnce(new Error("422"));
    const { result } = renderHook(() => useReassignFromSimilar(4), { wrapper });
    await act(async () => {
      await expect(result.current.mutateAsync({ jobIds: [9], candidateIds: [] })).rejects.toThrow("422");
    });
    expect(invalidated(["kanban", 4])).toBe(false);
  });
});
