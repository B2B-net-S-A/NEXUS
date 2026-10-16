import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/store/auth", () => ({
  useAuthStore: () => ({ token: "test-token" }),
}));
vi.mock("@/hooks/useHasInterviewsWindow", () => ({
  useHasInterviewsWindow: () => false,
}));

import { NotificationsRealtime } from "../NotificationsRealtime";
import { NOTIFICATION_FRAME_EVENT } from "@/lib/notification-topics";
import { useRealtimeStatus } from "@/store/realtime";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    FakeWebSocket.instances.push(this);
  }
  send() {}
  close() {}
}

function renderRealtime() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NotificationsRealtime />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  useRealtimeStatus.setState({ connected: false });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("NotificationsRealtime — jedyne gniazdo powiadomień (16.10.2026)", () => {
  it("otwiera dokładnie jedno gniazdo i przekazuje jego stan okienkom", () => {
    const view = renderRealtime();
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => FakeWebSocket.instances[0].onopen?.());
    expect(useRealtimeStatus.getState().connected).toBe(true);

    act(() => FakeWebSocket.instances[0].onclose?.());
    expect(useRealtimeStatus.getState().connected).toBe(false);
    view.unmount();
  });

  it("ramkę powiadomienia rozgłasza zdarzeniem okna — dzwonek nie trzyma gniazda", () => {
    const seen: unknown[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(NOTIFICATION_FRAME_EVENT, listener);
    renderRealtime();
    const ws = FakeWebSocket.instances[0];
    act(() => ws.onopen?.());
    const data = {
      id: 3,
      title: "CV gotowe do sprawdzenia: Ewa Lis",
      message: "Analityk danych",
      link: "/jobs/4?candidate=9&panel=cv",
      notification_type: "cv_ready",
      created_at: "2026-10-16T09:00:00Z",
      topic: "cv",
      toast: true,
    };
    act(() => ws.onmessage?.({ data: JSON.stringify({ type: "notification", data }) }));
    window.removeEventListener(NOTIFICATION_FRAME_EVENT, listener);
    expect(seen).toEqual([data]);
  });
});
