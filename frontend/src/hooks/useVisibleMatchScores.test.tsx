import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const matchScores = vi.fn();

vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: {
    matchScores: (...args: unknown[]) => matchScores(...args),
  },
}));

import {
  MATCH_SCORES_MAX_CANDIDATES,
  pickScoreRequestIds,
  useVisibleMatchScores,
} from "./useVisibleMatchScores";

const rows = (ids: number[]) => ids.map((id) => ({ id }));
const range = (from: number, to: number) =>
  Array.from({ length: to - from + 1 }, (_, i) => from + i);

describe("pickScoreRequestIds", () => {
  it("takes visible, not-yet-requested ids in display order, capped", () => {
    const order = [5, 4, 3, 2, 1];
    expect(pickScoreRequestIds(order, new Set([1, 3, 5]), new Set([5]), 1)).toEqual([
      3,
    ]);
    expect(pickScoreRequestIds(order, new Set([1, 3]), new Set())).toEqual([3, 1]);
    expect(MATCH_SCORES_MAX_CANDIDATES).toBe(20);
  });
});

describe("useVisibleMatchScores", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    matchScores.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("asks only for rows that became visible, at most 20 per request", async () => {
    matchScores.mockImplementation((_job: number, ids: number[]) =>
      Promise.resolve({
        scores: Object.fromEntries(ids.map((id) => [String(id), id])),
        breakdowns: {},
      }),
    );
    const items = rows(range(1, 50));
    const { result } = renderHook(() => useVisibleMatchScores(7, items));

    act(() => {
      // 25 rows on a tall screen, reported out of order, one of them twice.
      for (const id of [...range(2, 25).reverse(), 1, 3]) {
        result.current.onRowVisible(id);
      }
    });
    expect(matchScores).not.toHaveBeenCalled(); // gathered in one window
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    expect(matchScores).toHaveBeenCalledTimes(2);
    expect(matchScores.mock.calls[0]).toEqual([7, range(1, 20)]);
    expect(matchScores.mock.calls[1]).toEqual([7, range(21, 25)]);
    expect(result.current.scores["25"]).toBe(25);
    expect(result.current.scores["26"]).toBeUndefined(); // never on screen

    // Seeing the same rows again (scroll back) does not ask again.
    act(() => result.current.onRowVisible(5));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(matchScores).toHaveBeenCalledTimes(2);
  });

  it("starts over for a new result set and drops a late answer for the old one", async () => {
    let answerOld!: (value: unknown) => void;
    matchScores.mockImplementationOnce(
      () => new Promise((resolve) => (answerOld = resolve)),
    );
    const first = rows([1, 2]);
    const { result, rerender } = renderHook(
      ({ items }) => useVisibleMatchScores(7, items),
      { initialProps: { items: first } },
    );
    act(() => result.current.onRowVisible(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(matchScores).toHaveBeenCalledTimes(1);

    // A new search replaces the rows (same ids included) before the answer.
    matchScores.mockResolvedValueOnce({ scores: { "1": 90 }, breakdowns: {} });
    rerender({ items: rows([1, 3]) });
    expect(result.current.scores).toEqual({});
    act(() => result.current.onRowVisible(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(matchScores).toHaveBeenCalledTimes(2);
    expect(result.current.scores).toEqual({ "1": 90 });

    await act(async () => {
      answerOld({ scores: { "1": 11, "2": 12 }, breakdowns: {} });
    });
    expect(result.current.scores).toEqual({ "1": 90 });
  });

  it("outside a recruitment context never asks", async () => {
    const { result } = renderHook(() => useVisibleMatchScores(undefined, rows([1])));
    act(() => result.current.onRowVisible(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(matchScores).not.toHaveBeenCalled();
  });

  it("a failed request leaves rows without a badge and is not retried", async () => {
    matchScores.mockRejectedValue(new Error("503"));
    const { result } = renderHook(() => useVisibleMatchScores(7, rows([1])));
    act(() => result.current.onRowVisible(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(matchScores).toHaveBeenCalledTimes(1);
    expect(result.current.scores).toEqual({});
  });
});
