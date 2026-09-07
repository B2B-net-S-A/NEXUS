import { act, renderHook } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  SIDEBAR_PINNED_KEY,
  useSidebarPinned,
} from "@/components/v2/shell/useSidebarPinned";

function SidebarStateProbe() {
  const [pinned] = useSidebarPinned();
  return <span>{pinned ? "expanded" : "collapsed"}</span>;
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("useSidebarPinned", () => {
  it("nie czyta localStorage podczas renderu serwerowego", () => {
    window.localStorage.setItem(SIDEBAR_PINNED_KEY, "false");
    const getItem = vi.spyOn(Storage.prototype, "getItem");

    const html = renderToString(<SidebarStateProbe />);

    expect(html).toContain("expanded");
    expect(getItem).not.toHaveBeenCalled();
  });

  it("stosuje zapamiętane zwinięcie dopiero po zamontowaniu", () => {
    window.localStorage.setItem(SIDEBAR_PINNED_KEY, "false");

    const { result } = renderHook(() => useSidebarPinned());

    expect(result.current[0]).toBe(false);
  });

  it("zapisuje zmianę w dotychczasowym formacie true/false", () => {
    const { result } = renderHook(() => useSidebarPinned());

    act(() => result.current[1]((previous) => !previous));

    expect(result.current[0]).toBe(false);
    expect(window.localStorage.getItem(SIDEBAR_PINNED_KEY)).toBe("false");
  });

  it("nie wywraca sidebara, gdy storage jest niedostępny", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });

    const { result } = renderHook(() => useSidebarPinned());
    expect(result.current[0]).toBe(true);

    expect(() => act(() => result.current[1](false))).not.toThrow();
    expect(result.current[0]).toBe(false);
  });
});
