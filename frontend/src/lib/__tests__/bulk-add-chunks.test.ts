import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { post: (...args: unknown[]) => post(...args) },
}));

import { BULK_ADD_CHUNK, proposalsBulkApi } from "@/lib/candidate-search-api";

describe("proposalsBulkApi.addInChunks (U3, audyt 06.10.2026)", () => {
  beforeEach(() => {
    post.mockReset().mockImplementation(async (_url: string, body: { candidate_ids: number[] }) => ({
      data: {
        added: body.candidate_ids.filter((id) => id !== 7),
        skipped: body.candidate_ids.includes(7)
          ? [{ candidate_id: 7, reason: "already_in_job" }]
          : [],
        warnings: [],
        total_added: body.candidate_ids.filter((id) => id !== 7).length,
        total_skipped: body.candidate_ids.includes(7) ? 1 : 0,
      },
    }));
  });

  it("ponad 100 osób idzie paczkami po 100 i wynik jest jeden", async () => {
    const ids = Array.from({ length: 230 }, (_, i) => i + 1);
    const result = await proposalsBulkApi.addInChunks(5, {
      candidate_ids: ids,
      initial_stage_legacy: "new",
      source: "manual_search",
    });
    expect(BULK_ADD_CHUNK).toBe(100);
    expect(post).toHaveBeenCalledTimes(3);
    expect(post.mock.calls.map((c) => c[1].candidate_ids.length)).toEqual([100, 100, 30]);
    expect(post.mock.calls.every((c) => c[1].source === "manual_search")).toBe(true);
    expect(result.total_added).toBe(229);
    expect(result.skipped).toEqual([{ candidate_id: 7, reason: "already_in_job" }]);
  });

  it("do 100 osób — jedno żądanie", async () => {
    await proposalsBulkApi.addInChunks(5, { candidate_ids: [1, 2, 2, 3] });
    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0][1].candidate_ids).toEqual([1, 2, 3]);
  });
});
