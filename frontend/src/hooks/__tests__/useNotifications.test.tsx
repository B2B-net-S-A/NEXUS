import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/store/auth", () => ({
  useAuthStore: () => ({ token: "test-token" }),
}));

import { reconnectDelayMs, useNotifications } from "@/hooks/useNotifications";
import { NOTIFICATIONS_FALLBACK_POLL_MS } from "@/lib/polling";

/**
 * Reaudyt 14.09.2026: R02 (powrót gniazda nie odświeżał dzwonka, który przy
 * zdrowym WS odpytuje co 5 min) i R06 (ręczny fallback odpytywał także ukrytą
 * kartę; ponowne łączenie miało stałe opóźnienia, więc po deployu wszystkie
 * karty wracały jedną falą).
 */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  constructor() {
    FakeWebSocket.instances.push(this);
  }
  send() {}
  close() {}
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useNotifications(), { wrapper });
  const keys = () => invalidate.mock.calls.map((call) => JSON.stringify(call[0]?.queryKey));
  return { hook, invalidate, keys };
}

describe("useNotifications — powrót połączenia i fallback", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.spyOn(Math, "random").mockReturnValue(1);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  });

  it("pierwsze otwarcie nie odświeża, powrót po zerwaniu — tak", () => {
    const { hook, keys } = setup();
    const first = FakeWebSocket.instances[0];
    act(() => first.onopen?.());
    expect(keys()).toEqual([]);

    act(() => first.onclose?.());
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    const second = FakeWebSocket.instances[1];
    expect(second).toBeDefined();
    act(() => second.onopen?.());

    expect(keys()).toContain(JSON.stringify(["notifications"]));
    expect(keys()).toContain(JSON.stringify(["kpis", "me", "today"]));
    hook.unmount();
  });

  it("fallback nie odpytuje ukrytej karty", () => {
    const { hook, keys } = setup();
    const first = FakeWebSocket.instances[0];
    act(() => first.onopen?.());
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    act(() => first.onclose?.());
    // Blokujemy ponowne połączenie, żeby fallback pracował sam.
    vi.stubGlobal(
      "WebSocket",
      class {
        constructor() {
          throw new Error("offline");
        }
      },
    );
    act(() => {
      vi.advanceTimersByTime(NOTIFICATIONS_FALLBACK_POLL_MS * 2);
    });
    expect(keys()).toEqual([]);

    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    act(() => {
      vi.advanceTimersByTime(NOTIFICATIONS_FALLBACK_POLL_MS);
    });
    expect(keys()).toContain(JSON.stringify(["notifications"]));
    hook.unmount();
  });
});

describe("reconnectDelayMs", () => {
  it("rozrzuca opóźnienie w przedziale 50–100% wykładniczej bazy z sufitem 30 s", () => {
    expect(reconnectDelayMs(0, () => 0)).toBe(500);
    expect(reconnectDelayMs(0, () => 1)).toBe(1_000);
    expect(reconnectDelayMs(3, () => 0.5)).toBe(6_000);
    expect(reconnectDelayMs(10, () => 1)).toBe(30_000);
    expect(reconnectDelayMs(10, () => 0)).toBe(15_000);
  });
});
