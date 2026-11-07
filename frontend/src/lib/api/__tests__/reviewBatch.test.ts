import { describe, expect, it } from "vitest";

import { reviewBatchBlock } from "@/lib/api/reviewBatch";

describe("reviewBatchBlock", () => {
  it("rozpoznaje 423 porcji dnia", () => {
    const block = reviewBatchBlock({
      response: {
        status: 423,
        data: {
          detail: {
            code: "REVIEW_MINIMUM_PENDING",
            message: "Najpierw porcja od Nexusa: zostało 38 z 50 decyzji.",
            remaining: 38,
            required: 50,
          },
        },
      },
    });
    expect(block).toEqual({
      message: "Najpierw porcja od Nexusa: zostało 38 z 50 decyzji.",
      remaining: 38,
      required: 50,
    });
  });

  it("inne 423 i inne błędy to nie porcja", () => {
    expect(
      reviewBatchBlock({ response: { status: 423, data: { detail: { code: "CANDIDATE_CLAIMED" } } } }),
    ).toBeNull();
    expect(reviewBatchBlock({ response: { status: 500 } })).toBeNull();
    expect(reviewBatchBlock(new Error("x"))).toBeNull();
  });
});
