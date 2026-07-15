import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useCandidateSearchDebounce } from "@/hooks/useCandidateSearchDebounce";

describe("useCandidateSearchDebounce", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("commits only the latest draft after 300 ms", () => {
    const onCommit = vi.fn();
    const { rerender } = renderHook(
      ({ draft }) =>
        useCandidateSearchDebounce({ draft, committed: "", onCommit }),
      { initialProps: { draft: "p" } },
    );

    act(() => vi.advanceTimersByTime(200));
    rerender({ draft: "python" });
    act(() => vi.advanceTimersByTime(299));
    expect(onCommit).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith("python");
  });

  it("does not schedule a commit when draft already equals committed", () => {
    const onCommit = vi.fn();
    renderHook(() =>
      useCandidateSearchDebounce({
        draft: "python",
        committed: "python",
        onCommit,
      }),
    );
    act(() => vi.runAllTimers());
    expect(onCommit).not.toHaveBeenCalled();
  });
});
