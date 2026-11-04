import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { invalidateAfterPipelineMove } from "@/lib/pipeline-move-invalidation";

function keysInvalidated(qc: QueryClient): unknown[] {
  const spy = vi.spyOn(qc, "invalidateQueries");
  invalidateAfterPipelineMove(qc, 42, 7);
  return spy.mock.calls.map(([filters]) => (filters as { queryKey?: unknown }).queryKey);
}

describe("invalidateAfterPipelineMove — championi (D5, D7)", () => {
  it("rekrutacja z championami: nagłówek, lista i okienko championów od nowa", () => {
    const qc = new QueryClient();
    qc.setQueryData(["job", "42"], { champions: [{ candidate_id: 7, name: "Karol Wzorcowy" }] });
    const keys = keysInvalidated(qc);
    expect(keys).toContainEqual(["job", "42"]);
    expect(keys).toContainEqual(["jobs-v2"]);
    expect(keys).toContainEqual(["job-champions", 42]);
  });

  it("bez championów: tylko Tablica i panel osoby, jak dotąd", () => {
    const qc = new QueryClient();
    qc.setQueryData(["job", "42"], { champions: [] });
    const keys = keysInvalidated(qc);
    expect(keys).toContainEqual(["kanban", "42"]);
    expect(keys).not.toContainEqual(["jobs-v2"]);
  });
});
