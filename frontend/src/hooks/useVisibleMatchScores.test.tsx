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
  RATE_LIMIT_RETRY_BASE_MS,
  pickScoreRequestIds,
  scoreFailureFor,
  useVisibleMatchScores,
} from "./useVisibleMatchScores";

const rows = (ids: number[]) => ids.map((id) => ({ id }));
const range = (from: number, to: number) =>
  Array.from({ length: to - from + 1 }, (_, i) => from + i);
const httpError = (status: number) => Object.assign(new Error(`HTTP ${status}`), {
  response: { status },
});
const answer = (ids: number[], profile_key = "0:default") => ({
  scores: Object.fromEntries(ids.map((id) => [String(id), id])),
  breakdowns: {},
  profile_key,
});
const signalOf = (call: number) =>
  (matchScores.mock.calls[call][2] as { signal: AbortSignal }).signal;

async function settle(ms = 200) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

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

describe("scoreFailureFor", () => {
  it("403 is 'no access', everything else can be asked again", () => {
    expect(scoreFailureFor(httpError(403))).toBe("forbidden");
    expect(scoreFailureFor(httpError(429))).toBe("retry");
    expect(scoreFailureFor(httpError(503))).toBe("retry");
    expect(scoreFailureFor(new Error("Network Error"))).toBe("retry");
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
      Promise.resolve(answer(ids)),
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
    await settle();

    expect(matchScores).toHaveBeenCalledTimes(2);
    expect(matchScores.mock.calls[0].slice(0, 2)).toEqual([7, range(1, 20)]);
    expect(matchScores.mock.calls[1].slice(0, 2)).toEqual([7, range(21, 25)]);
    expect(signalOf(0)).toBeInstanceOf(AbortSignal);
    expect(result.current.scores["25"]).toBe(25);
    expect(result.current.scores["26"]).toBeUndefined(); // never on screen
    expect(result.current.failures).toEqual({});

    // Seeing the same rows again (scroll back) does not ask again.
    act(() => result.current.onRowVisible(5));
    await settle();
    expect(matchScores).toHaveBeenCalledTimes(2);
  });

  it("starts over for a new result set, cancels and drops the old one's request", async () => {
    let answerOld!: (value: unknown) => void;
    matchScores.mockImplementationOnce(
      () => new Promise((resolve) => (answerOld = resolve)),
    );
    const { result, rerender } = renderHook(
      ({ items }) => useVisibleMatchScores(7, items),
      { initialProps: { items: rows([1, 2]) } },
    );
    act(() => result.current.onRowVisible(1));
    await settle();
    expect(matchScores).toHaveBeenCalledTimes(1);

    // A new search replaces the rows (same ids included) before the answer.
    matchScores.mockResolvedValueOnce({ ...answer([]), scores: { "1": 90 } });
    rerender({ items: rows([1, 3]) });
    expect(signalOf(0).aborted).toBe(true);
    expect(result.current.scores).toEqual({});
    act(() => result.current.onRowVisible(1));
    await settle();
    expect(matchScores).toHaveBeenCalledTimes(2);
    expect(result.current.scores).toEqual({ "1": 90 });

    await act(async () => {
      answerOld(answer([1, 2]));
    });
    expect(result.current.scores).toEqual({ "1": 90 });
  });

  it("unmounting cancels what is still in flight", async () => {
    matchScores.mockImplementation(() => new Promise(() => {}));
    const items = rows([1]);
    const { result, unmount } = renderHook(() => useVisibleMatchScores(7, items));
    act(() => result.current.onRowVisible(1));
    await settle();

    unmount();

    expect(signalOf(0).aborted).toBe(true);
  });

  it("outside a recruitment context never asks", async () => {
    const items = rows([1]);
    const { result } = renderHook(() => useVisibleMatchScores(undefined, items));
    act(() => result.current.onRowVisible(1));
    await settle();
    expect(matchScores).not.toHaveBeenCalled();
  });

  it("a failed request marks its rows 'retry' — asked again only on demand", async () => {
    matchScores.mockRejectedValueOnce(httpError(503));
    const items = rows([1, 2]);
    const { result } = renderHook(() => useVisibleMatchScores(7, items));
    act(() => {
      result.current.onRowVisible(1);
      result.current.onRowVisible(2);
    });
    await settle(60_000);

    // Not a silent empty cell, and no loop.
    expect(matchScores).toHaveBeenCalledTimes(1);
    expect(result.current.scores).toEqual({});
    expect(result.current.failures).toEqual({ "1": "retry", "2": "retry" });

    matchScores.mockResolvedValueOnce(answer([1, 2]));
    act(() => result.current.retry());
    // Back to "being measured" until the answer, then scored.
    expect(result.current.failures).toEqual({});
    await settle();
    expect(matchScores).toHaveBeenCalledTimes(2);
    expect(matchScores.mock.calls[1].slice(0, 2)).toEqual([7, [1, 2]]);
    expect(result.current.scores).toEqual({ "1": 1, "2": 2 });
  });

  it("a 429 is retried on its own with back-off", async () => {
    matchScores
      .mockRejectedValueOnce(httpError(429))
      .mockRejectedValueOnce(httpError(429))
      .mockResolvedValueOnce(answer([1]));
    const items = rows([1]);
    const { result } = renderHook(() => useVisibleMatchScores(7, items));
    act(() => result.current.onRowVisible(1));
    await settle();
    expect(result.current.failures).toEqual({ "1": "retry" });

    await settle(RATE_LIMIT_RETRY_BASE_MS - 500);
    expect(matchScores).toHaveBeenCalledTimes(1); // still waiting
    await settle(1_000);
    expect(matchScores).toHaveBeenCalledTimes(2);
    // Second 429: the delay doubles.
    await settle(RATE_LIMIT_RETRY_BASE_MS + 500);
    expect(matchScores).toHaveBeenCalledTimes(2);
    await settle(RATE_LIMIT_RETRY_BASE_MS);
    expect(matchScores).toHaveBeenCalledTimes(3);
    expect(result.current.scores).toEqual({ "1": 1 });
    expect(result.current.failures).toEqual({});
  });

  it("a 403 marks the rows 'forbidden' and stops asking for this recruitment", async () => {
    matchScores.mockRejectedValueOnce(httpError(403));
    const items = rows([1, 2, 3]);
    const { result } = renderHook(() => useVisibleMatchScores(7, items));
    act(() => {
      result.current.onRowVisible(1);
      result.current.onRowVisible(2);
    });
    await settle();
    expect(result.current.failures).toEqual({ "1": "forbidden", "2": "forbidden" });

    act(() => result.current.onRowVisible(3));
    act(() => result.current.retry());
    await settle(60_000);

    expect(matchScores).toHaveBeenCalledTimes(1);
    expect(result.current.failures["3"]).toBe("forbidden");
  });

  it("scores of another weight profile never share the screen", async () => {
    matchScores
      .mockResolvedValueOnce(answer([1], "3:aaaaaaaaaaaa"))
      .mockResolvedValueOnce(answer([2], "4:bbbbbbbbbbbb"))
      .mockImplementation((_job: number, ids: number[]) =>
        Promise.resolve(answer(ids, "4:bbbbbbbbbbbb")),
      );
    const items = rows([1, 2]);
    const { result } = renderHook(() => useVisibleMatchScores(7, items));
    act(() => result.current.onRowVisible(1));
    await settle();
    expect(result.current.scores).toEqual({ "1": 1 });

    // The next answer comes under another profile (an admin switched it).
    act(() => result.current.onRowVisible(2));
    await settle();

    // Row 1 was scored under the old profile: dropped and asked again.
    expect(matchScores).toHaveBeenCalledTimes(3);
    expect(matchScores.mock.calls[2].slice(0, 2)).toEqual([7, [1]]);
    expect(result.current.scores).toEqual({ "1": 1, "2": 2 });
  });
});
