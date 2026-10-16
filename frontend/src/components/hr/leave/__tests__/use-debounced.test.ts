import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebounced } from "../LeaveRequestDialog";

describe("useDebounced w oknie wniosku", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("obiekt budowany na nowo w każdym renderze dogania wartość i nie zapętla renderów", () => {
    let renders = 0;
    const { result, rerender } = renderHook(
      ({ start }: { start: string }) => {
        renders += 1;
        // Jak w oknie: nowy obiekt przy każdym renderze, ta sama treść.
        return useDebounced({ start, end: start }, 300);
      },
      { initialProps: { start: "2026-10-16" } },
    );
    rerender({ start: "2026-10-19" });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current).toEqual({ start: "2026-10-19", end: "2026-10-19" });
    const settled = renders;
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    // Po dogonieniu nic się nie dzieje — wcześniej render co 300 ms bez końca
    // resetował drugi zegar (podgląd wniosku) i „Wyślij” zostawał zablokowany.
    expect(renders).toBe(settled);
  });
});
