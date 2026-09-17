import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ msg: "7" as string | null }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: (key: string) => (key === "msg" ? nav.msg : null) }),
}));

import {
  CHAT_MESSAGE_HIGHLIGHT_MS,
  useChatMessageFocus,
} from "@/hooks/useChatMessageFocus";

beforeEach(() => {
  vi.useFakeTimers();
  nav.msg = "7";
  window.history.replaceState(null, "", "/jobs/1?tab=chat&msg=7");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useChatMessageFocus", () => {
  it("podświetlenie gaśnie, choć zdjęcie `msg` z adresu zmienia parametry", () => {
    const { result, rerender } = renderHook(
      ({ ids }) => useChatMessageFocus({ messageIds: ids, ready: true }),
      { initialProps: { ids: [5, 7] } },
    );
    expect(result.current).toBe(7);
    expect(window.location.search).not.toContain("msg=");

    // Next synchronizuje `replaceState` z `useSearchParams` — parametr znika.
    nav.msg = null;
    rerender({ ids: [5, 7] });
    expect(result.current).toBe(7);

    act(() => {
      vi.advanceTimersByTime(CHAT_MESSAGE_HIGHLIGHT_MS + 10);
    });
    expect(result.current).toBeNull();
  });
});
