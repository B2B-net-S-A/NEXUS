import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import {
  fetchCandidateListPage,
  getCandidateListIncludeFlags,
  getCandidateListViewState,
} from "@/components/v2/pages/candidate-list-query";

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn() },
}));

const apiGet = vi.mocked(api.get);

describe("getCandidateListIncludeFlags", () => {
  it("does not request heavy enrichments for a minimal table", () => {
    expect(
      getCandidateListIncludeFlags("list", new Set(["candidate", "contact"])),
    ).toEqual({
      includeMatchStats: false,
      includeActiveRecruitments: false,
      includeLastActivity: false,
    });
  });

  it("enables only the enrichments required by visible grouped columns", () => {
    expect(
      getCandidateListIncludeFlags(
        "list",
        new Set(["candidate", "process", "activity", "match"]),
      ),
    ).toEqual({
      includeMatchStats: true,
      includeActiveRecruitments: true,
      includeLastActivity: true,
    });
  });

  it("enables all enrichments for tiles", () => {
    expect(getCandidateListIncludeFlags("tiles", new Set())).toEqual({
      includeMatchStats: true,
      includeActiveRecruitments: true,
      includeLastActivity: true,
    });
  });
});

describe("candidate list request and states", () => {
  beforeEach(() => apiGet.mockReset());

  it("passes React Query's AbortSignal to the canonical request", async () => {
    const controller = new AbortController();
    apiGet.mockResolvedValue({ data: { items: [], total: 0 } } as never);

    await fetchCandidateListPage({ q: "python", page: 1 }, controller.signal);

    expect(apiGet).toHaveBeenCalledWith("/api/candidates", {
      params: { q: "python", page: 1 },
      paramsSerializer: { indexes: null },
      signal: controller.signal,
    });
  });

  it.each([
    [{ isLoading: true, isError: false, itemCount: 0 }, "initial-loading"],
    [{ isLoading: false, isError: true, itemCount: 0 }, "error"],
    [{ isLoading: false, isError: true, itemCount: 2 }, "refresh-error"],
    [{ isLoading: false, isError: false, itemCount: 0 }, "empty"],
    [{ isLoading: false, isError: false, itemCount: 2 }, "ready"],
  ] as const)("maps %o to %s", (input, expected) => {
    expect(getCandidateListViewState(input)).toBe(expected);
  });
});
