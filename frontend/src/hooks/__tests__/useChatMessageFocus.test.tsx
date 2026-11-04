import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ msg: "7" as string | null }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: (key: string) => (key === "msg" ? nav.msg : null) }),
}));

import {
  CHAT_FOCUS_MAX_OLDER_PAGES,
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

  it("doczytuje starsze strony, aż znajdzie wskazaną wiadomość", () => {
    const loadMore = vi.fn();
    const { result, rerender } = renderHook(
      ({ ids, loading }) =>
        useChatMessageFocus({
          messageIds: ids,
          ready: true,
          hasMore: true,
          isLoadingMore: loading,
          loadMore,
        }),
      { initialProps: { ids: [20, 21], loading: false } },
    );
    // Wiadomości 7 nie ma na pierwszej stronie — parametr zostaje w adresie.
    expect(loadMore).toHaveBeenCalledTimes(1);
    expect(result.current).toBeNull();
    expect(window.location.search).toContain("msg=7");

    // W trakcie pobierania nie prosimy o kolejną stronę.
    rerender({ ids: [20, 21], loading: true });
    expect(loadMore).toHaveBeenCalledTimes(1);

    rerender({ ids: [10, 11, 20, 21], loading: false });
    expect(loadMore).toHaveBeenCalledTimes(2);

    rerender({ ids: [10, 11, 20, 21], loading: true });
    rerender({ ids: [6, 7, 10, 11, 20, 21], loading: false });
    expect(loadMore).toHaveBeenCalledTimes(2);
    expect(result.current).toBe(7);
    expect(window.location.search).not.toContain("msg=");
  });

  it("po limicie stron przestaje szukać i zdejmuje parametr", () => {
    const loadMore = vi.fn();
    const { result, rerender } = renderHook(
      ({ ids, loading }) =>
        useChatMessageFocus({
          messageIds: ids,
          ready: true,
          hasMore: true,
          isLoadingMore: loading,
          loadMore,
        }),
      { initialProps: { ids: [1000], loading: false } },
    );
    for (let page = 1; page <= CHAT_FOCUS_MAX_OLDER_PAGES + 2; page += 1) {
      rerender({ ids: [1000 - page, 1000], loading: true });
      rerender({ ids: [1000 - page, 1000], loading: false });
    }
    expect(loadMore).toHaveBeenCalledTimes(CHAT_FOCUS_MAX_OLDER_PAGES);
    expect(result.current).toBeNull();
    expect(window.location.search).not.toContain("msg=");
  });

  it("bez starszych stron zachowuje się jak dotąd: parametr znika, nic nie podświetla", () => {
    const loadMore = vi.fn();
    const { result } = renderHook(() =>
      useChatMessageFocus({
        messageIds: [20, 21],
        ready: true,
        hasMore: false,
        loadMore,
      }),
    );
    expect(loadMore).not.toHaveBeenCalled();
    expect(result.current).toBeNull();
    expect(window.location.search).not.toContain("msg=");
  });
});
