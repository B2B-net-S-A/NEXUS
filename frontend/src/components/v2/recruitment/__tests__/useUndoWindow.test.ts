import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UNDO_ADD_WINDOW_MS, useUndoWindow } from "../useUndoWindow";

describe("useUndoWindow — „Cofnij” tylko zaraz po dodaniu", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("po 15 minutach osoba wypada z okna, a ponowne dodanie liczy od nowa", () => {
    const { result } = renderHook(() => useUndoWindow());
    act(() => result.current.start([7]));
    expect(result.current.expired.has(7)).toBe(false);

    act(() => vi.advanceTimersByTime(UNDO_ADD_WINDOW_MS));
    expect(result.current.expired.has(7)).toBe(true);

    act(() => result.current.start([7]));
    expect(result.current.expired.has(7)).toBe(false);
  });
});
