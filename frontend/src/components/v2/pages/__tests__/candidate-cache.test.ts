import { describe, expect, it, vi } from "vitest";

import {
  candidateInvalidationKeys,
  invalidateCandidateMutation,
} from "@/components/v2/pages/candidate-cache";

describe("candidate mutation cache invalidation", () => {
  it("defines exact invalidations for assignment, note, edit, rate and document", () => {
    expect(candidateInvalidationKeys("42", "assignment")).toEqual([
      ["candidate-history", 42],
      ["suggested-jobs", 42],
      ["candidate-pipelines", 42],
      ["candidates-v2"],
    ]);
    expect(candidateInvalidationKeys(42, "note")).toEqual([
      ["candidate-timeline", 42],
      ["candidate-notes", 42],
      ["candidate-ai-profile", 42],
      ["suggested-jobs", 42],
    ]);
    expect(candidateInvalidationKeys(42, "edit")).toEqual([
      ["candidate", 42],
      ["candidate-ai-profile", 42],
      ["suggested-jobs", 42],
      ["candidates-v2"],
    ]);
    expect(candidateInvalidationKeys(42, "rate")).toContainEqual([
      "suggested-jobs",
      42,
    ]);
    expect(candidateInvalidationKeys(42, "document")).toContainEqual([
      "candidate-documents",
      42,
    ]);
  });

  it("invalidates every key through React Query", () => {
    const invalidateQueries = vi.fn();
    invalidateCandidateMutation(
      { invalidateQueries } as never,
      42,
      "rate",
    );
    expect(invalidateQueries).toHaveBeenCalledTimes(4);
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["suggested-jobs", 42],
    });
  });
});
