import { describe, expect, it } from "vitest";

import { boardReviewCountLabel, boardReviewState } from "@/lib/board-review-state";

const ok = {
  settled: true,
  inboxError: false,
  similarError: false,
  recommendationsError: false,
  runError: false,
  count: 0,
};

describe("boardReviewState (REC-02)", () => {
  it("pustka tylko po odpowiedzi wszystkich źródeł", () => {
    expect(boardReviewState(ok).kind).toBe("empty");
    expect(boardReviewState({ ...ok, settled: false }).kind).toBe("loading");
  });

  it("awaria przy pustej liście = error z nazwą źródła", () => {
    const state = boardReviewState({ ...ok, similarError: true });
    expect(state).toEqual({ kind: "error", failed: ["podobne projekty"] });
  });

  it("awaria przy niepustej liście = partial", () => {
    expect(boardReviewState({ ...ok, inboxError: true, count: 3 }).kind).toBe("partial");
  });

  it("lista", () => {
    expect(boardReviewState({ ...ok, count: 2 }).kind).toBe("list");
    expect(boardReviewState({ ...ok, settled: false, count: 2 }).kind).toBe("list");
  });

  it("licznik z kolejną stroną skrzynki", () => {
    expect(boardReviewCountLabel(50, true)).toBe("50+");
    expect(boardReviewCountLabel(7, false)).toBe("7");
  });
});
