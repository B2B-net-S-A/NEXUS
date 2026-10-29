import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { composeKeyAction, useChatCompose } from "@/components/v2/pages/chat-compose";

const key = (k: string, mods: Partial<{ shiftKey: boolean; ctrlKey: boolean; metaKey: boolean }> = {}) => ({
  key: k,
  shiftKey: false,
  ctrlKey: false,
  metaKey: false,
  ...mods,
});

describe("composeKeyAction", () => {
  it("zwykłe pole: Enter wysyła, Shift+Enter dodaje linię, Esc anuluje odpowiedź/edycję", () => {
    expect(composeKeyAction(key("Enter"), false)).toBe("send");
    expect(composeKeyAction(key("Enter", { shiftKey: true }), false)).toBeNull();
    expect(composeKeyAction(key("Escape"), false)).toBe("cancel");
    expect(composeKeyAction(key("a"), false)).toBeNull();
  });

  it("rozwinięte pole: Enter dodaje linię, Ctrl/⌘+Enter wysyła, Esc zwija", () => {
    expect(composeKeyAction(key("Enter"), true)).toBeNull();
    expect(composeKeyAction(key("Enter", { shiftKey: true }), true)).toBeNull();
    expect(composeKeyAction(key("Enter", { ctrlKey: true }), true)).toBe("send");
    expect(composeKeyAction(key("Enter", { metaKey: true }), true)).toBe("send");
    expect(composeKeyAction(key("Escape"), true)).toBe("collapse");
  });
});

function scrollableList(scrollTop: number, scrollHeight = 900): HTMLDivElement {
  const el = document.createElement("div");
  let top = scrollTop;
  Object.defineProperty(el, "scrollTop", { get: () => top, set: (v: number) => (top = v), configurable: true });
  Object.defineProperty(el, "scrollHeight", { value: scrollHeight, configurable: true });
  return el;
}

describe("useChatCompose", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("obserwuje nową listę po jej ponownym zamontowaniu (widok błędu → „Spróbuj ponownie”)", () => {
    const observed: Element[] = [];
    const disconnect = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe(el: Element) {
          observed.push(el);
        }
        disconnect = disconnect;
      },
    );
    const listRef = { current: null as HTMLDivElement | null };
    const stickRef = { current: true };
    const { result } = renderHook(() => useChatCompose(listRef, stickRef));

    const first = scrollableList(0);
    const cleanup = result.current.listCallbackRef(first);
    if (typeof cleanup === "function") cleanup();
    result.current.listCallbackRef(null);
    const second = scrollableList(0);
    result.current.listCallbackRef(second);

    expect(observed).toEqual([first, second]);
    expect(disconnect).toHaveBeenCalledTimes(1);
    expect(listRef.current).toBe(second);
  });

  it("po zwinięciu pola lista wraca tam, gdzie osoba czytała, albo na dół", () => {
    const list = scrollableList(240);
    const listRef = { current: list as HTMLDivElement | null };
    const stickRef = { current: false };
    const { result } = renderHook(() => useChatCompose(listRef, stickRef));

    act(() => result.current.setComposeExpanded(true));
    list.scrollTop = 0; // `hidden` zeruje przewinięcie
    act(() => result.current.setComposeExpanded(false));
    expect(list.scrollTop).toBe(240);

    stickRef.current = true;
    act(() => result.current.setComposeExpanded(true));
    act(() => result.current.setComposeExpanded(false));
    expect(list.scrollTop).toBe(900);
  });
});
