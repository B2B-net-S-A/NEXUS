import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePresence, type PresenceViewer } from "@/hooks/usePresence";
import {
  PRESENCE_EVENT,
  WS_OPEN_EVENT,
  activePresenceKeys,
  clearWsSender,
  setWsSender,
} from "@/lib/wsBus";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

function viewer(user_id: number, name: string): PresenceViewer {
  return { user_id, name, email: `${name}@example.com`, role: "recruiter", editing: [], since: null };
}

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

const sent: Record<string, unknown>[] = [];

beforeEach(() => {
  sent.length = 0;
  mocks.get.mockReset();
  setWsSender((msg) => sent.push(msg));
  activePresenceKeys.clear();
});

afterEach(() => {
  clearWsSender();
  vi.useRealTimers();
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
});

describe("usePresence", () => {
  it("bez id zasobu nie pyta API i nie subskrybuje", () => {
    const { result } = renderHook(() => usePresence("candidate", null), {
      wrapper: wrapper(),
    });
    result.current.setEditing("notes", true);
    expect(mocks.get).not.toHaveBeenCalled();
    expect(sent).toEqual([]);
    expect(result.current.viewers).toEqual([]);
  });

  it("seeduje widzów z API, subskrybuje i przyjmuje tylko własne aktualizacje", async () => {
    mocks.get.mockResolvedValue({ data: { viewers: [viewer(1, "anna")] } });

    const { result, unmount } = renderHook(() => usePresence("candidate", 5), {
      wrapper: wrapper(),
    });

    expect(sent).toContainEqual({ type: "presence:subscribe", resource_type: "candidate", resource_id: 5 });
    expect(activePresenceKeys.has("candidate:5")).toBe(true);
    await waitFor(() => expect(result.current.viewers.map((v) => v.name)).toEqual(["anna"]));
    expect(mocks.get).toHaveBeenCalledWith("/api/presence/candidate/5/viewers");

    act(() => {
      window.dispatchEvent(
        new CustomEvent(PRESENCE_EVENT, {
          detail: { type: "presence:update", resource_type: "candidate", resource_id: 6, viewers: [viewer(9, "obcy")] },
        }),
      );
      window.dispatchEvent(
        new CustomEvent(PRESENCE_EVENT, {
          detail: { type: "presence:update", resource_type: "job", resource_id: 5, viewers: [viewer(9, "obcy")] },
        }),
      );
    });
    expect(result.current.viewers.map((v) => v.name)).toEqual(["anna"]);

    act(() => {
      window.dispatchEvent(
        new CustomEvent(PRESENCE_EVENT, {
          detail: { type: "presence:update", resource_type: "candidate", resource_id: 5, viewers: [viewer(2, "bartek")] },
        }),
      );
    });
    expect(result.current.viewers.map((v) => v.name)).toEqual(["bartek"]);

    unmount();
    expect(sent.at(-1)).toEqual({ type: "presence:unsubscribe", resource_type: "candidate", resource_id: 5 });
    expect(activePresenceKeys.has("candidate:5")).toBe(false);
  });

  it("ponawia subskrypcję po reconnect WS i odpina się przy ukryciu karty", async () => {
    mocks.get.mockResolvedValue({ data: { viewers: [] } });
    renderHook(() => usePresence("job", 3), { wrapper: wrapper() });
    sent.length = 0;

    act(() => {
      window.dispatchEvent(new Event(WS_OPEN_EVENT));
    });
    expect(sent).toEqual([{ type: "presence:subscribe", resource_type: "job", resource_id: 3 }]);

    sent.length = 0;
    act(() => setVisibility("hidden"));
    expect(sent).toContainEqual({ type: "presence:unsubscribe", resource_type: "job", resource_id: 3 });

    sent.length = 0;
    act(() => setVisibility("visible"));
    expect(sent).toEqual([{ type: "presence:subscribe", resource_type: "job", resource_id: 3 }]);
  });

  it("zmiana zasobu odpina stary i subskrybuje nowy", () => {
    mocks.get.mockResolvedValue({ data: { viewers: [] } });
    const { rerender } = renderHook(({ id }) => usePresence("candidate", id), {
      wrapper: wrapper(),
      initialProps: { id: 1 },
    });
    sent.length = 0;

    rerender({ id: 2 });

    expect(sent).toContainEqual({ type: "presence:unsubscribe", resource_type: "candidate", resource_id: 1 });
    expect(sent).toContainEqual({ type: "presence:subscribe", resource_type: "candidate", resource_id: 2 });
    expect(activePresenceKeys.has("candidate:1")).toBe(false);
    expect(activePresenceKeys.has("candidate:2")).toBe(true);
  });

  it("dławi start edycji, a jej koniec wysyła od razu i bez duplikatów", () => {
    vi.useFakeTimers();
    mocks.get.mockResolvedValue({ data: { viewers: [] } });
    const { result } = renderHook(() => usePresence("candidate", 5), { wrapper: wrapper() });
    sent.length = 0;
    const editing = (active: boolean) => ({
      type: "presence:editing",
      resource_type: "candidate",
      resource_id: 5,
      field: "notes",
      active,
    });

    act(() => {
      result.current.setEditing("notes", true);
      result.current.setEditing("notes", true);
    });
    expect(sent).toEqual([]);
    act(() => vi.advanceTimersByTime(400));
    expect(sent).toEqual([editing(true)]);

    // Szybkie focus→blur: start anulowany, a „koniec” nic nie zmienia (już true→false raz).
    act(() => {
      result.current.setEditing("notes", false);
      result.current.setEditing("notes", false);
    });
    expect(sent).toEqual([editing(true), editing(false)]);

    act(() => {
      result.current.setEditing("notes", true);
      result.current.setEditing("notes", false);
      vi.advanceTimersByTime(1000);
    });
    expect(sent).toEqual([editing(true), editing(false)]);
  });

  it("utrata focusu okna czyści aktywne flagi edycji", () => {
    vi.useFakeTimers();
    mocks.get.mockResolvedValue({ data: { viewers: [] } });
    const { result } = renderHook(() => usePresence("candidate", 5), { wrapper: wrapper() });
    act(() => {
      result.current.setEditing("title", true);
      vi.advanceTimersByTime(400);
    });
    sent.length = 0;

    act(() => {
      window.dispatchEvent(new Event("blur"));
    });

    expect(sent).toEqual([
      { type: "presence:editing", resource_type: "candidate", resource_id: 5, field: "title", active: false },
    ]);
  });
});
