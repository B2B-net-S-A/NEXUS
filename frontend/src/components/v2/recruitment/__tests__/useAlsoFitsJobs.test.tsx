import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  add: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("@/lib/also-fits-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/also-fits-api")>();
  return { ...actual, alsoFitsApi: { get: mocks.get } };
});
vi.mock("@/lib/candidate-search-api", () => ({ proposalsBulkApi: { add: mocks.add } }));
vi.mock("@/lib/api", () => ({ candidatesApi: { removeFromRecruitment: mocks.remove } }));

import { elsewhereRefusal, useAlsoFitsJobs } from "../useAlsoFitsJobs";

const JOB = { job_id: 21, title: "Angular Developer", client_name: null, score: 84, matching_must: [], gap_must: [] };

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

afterEach(() => vi.clearAllMocks());

describe("useAlsoFitsJobs", () => {
  it("asks only for people added in this window and adds to another job with the also_fits source", async () => {
    mocks.get.mockResolvedValue({ candidate_id: 7, from_job_id: 10, status: "ok", jobs: [JOB] });
    mocks.add.mockResolvedValue({ added: [7], skipped: [], total_added: 1, total_skipped: 0 });
    const { result } = renderHook(
      () => useAlsoFitsJobs({ fromJobId: 10, addedIds: new Set([7]), enabled: true }),
      { wrapper: wrapper() },
    );
    expect(result.current.forCandidate(8)).toBeNull();
    await waitFor(() => expect(result.current.forCandidate(7)?.status).toBe("ok"));
    expect(mocks.get).toHaveBeenCalledWith(7, 10);
    expect(result.current.forCandidate(7)?.jobs).toEqual([JOB]);

    act(() => result.current.add(7, [21]));
    expect(result.current.forCandidate(7)?.stateOf(21)).toBe("adding");
    await waitFor(() => expect(result.current.forCandidate(7)?.stateOf(21)).toBe("added"));
    expect(mocks.add).toHaveBeenCalledWith(21, {
      candidate_ids: [7],
      initial_stage_legacy: "new",
      source: "also_fits",
      origin_job_id: 10,
    });
    expect(result.current.forCandidate(7)?.undoable(21)).toBe(true);

    mocks.remove.mockResolvedValue({});
    act(() => result.current.undo(7, 21));
    await waitFor(() => expect(result.current.forCandidate(7)?.stateOf(21)).toBeUndefined());
    expect(mocks.remove).toHaveBeenCalledWith(7, 21, { quickUndo: true });
  });

  it("keeps the job addable and shows the server refusal when the add is skipped", async () => {
    mocks.get.mockResolvedValue({ candidate_id: 7, from_job_id: 10, status: "ok", jobs: [JOB] });
    mocks.add.mockResolvedValue({
      added: [],
      skipped: [{ candidate_id: 7, reason: "closed_in_job", reason_label: null }],
      total_added: 0,
      total_skipped: 1,
    });
    const { result } = renderHook(
      () => useAlsoFitsJobs({ fromJobId: 10, addedIds: new Set([7]), enabled: true }),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.forCandidate(7)?.status).toBe("ok"));
    act(() => result.current.add(7, [21]));
    await waitFor(() => expect(result.current.forCandidate(7)?.errorOf(21)).toMatch(/zamkniętą kartę/));
    expect(result.current.forCandidate(7)?.stateOf(21)).toBeUndefined();
  });

  it("an API failure is an error state, not an empty list", async () => {
    mocks.get.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(
      () => useAlsoFitsJobs({ fromJobId: 10, addedIds: new Set([7]), enabled: true }),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.forCandidate(7)?.status).toBe("error"));
  });

  it("does not ask at all for a read-only viewer", () => {
    const { result } = renderHook(
      () => useAlsoFitsJobs({ fromJobId: 10, addedIds: new Set([7]), enabled: false }),
      { wrapper: wrapper() },
    );
    expect(result.current.forCandidate(7)).toBeNull();
    expect(mocks.get).not.toHaveBeenCalled();
  });
});

describe("elsewhereRefusal", () => {
  it("prefers the server label and maps known reasons", () => {
    expect(elsewhereRefusal({ candidate_id: 1, reason: "rejected_by_hiring_manager", reason_label: "Weto HM: X" })).toBe(
      "Weto HM: X",
    );
    expect(elsewhereRefusal({ candidate_id: 1, reason: "already_in_job" })).toMatch(/już w tej rekrutacji/);
    expect(elsewhereRefusal(undefined)).toBe("Nie dodano do tej rekrutacji.");
  });
});
