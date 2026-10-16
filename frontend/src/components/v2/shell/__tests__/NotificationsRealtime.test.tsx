import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/store/auth", () => ({
  useAuthStore: () => ({ token: "test-token" }),
}));
vi.mock("@/hooks/useHasInterviewsWindow", () => ({
  useHasInterviewsWindow: () => false,
}));
const push = vi.hoisted(() => vi.fn());
const showActionToast = vi.hoisted(() => vi.fn());
const showInfo = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showActionToast, showInfo }),
}));

import { NotificationsRealtime, shouldToastFrame } from "../NotificationsRealtime";
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
  useRealtimeStatus.setState({ connected: false, openTopic: null });
  push.mockReset();
  showActionToast.mockReset();
  showInfo.mockReset();
});

function deliver(data: Record<string, unknown>) {
  const ws = FakeWebSocket.instances[0];
  act(() => ws.onopen?.());
  act(() =>
    ws.onmessage?.({
      data: JSON.stringify({
        type: "notification",
        data: { id: 1, message: "m", created_at: "2026-10-16T09:00:00Z", ...data },
      }),
    }),
  );
}

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


describe("NotificationsRealtime — dymki według tematu", () => {
  it("dymek, gdy serwer pozwala; „Otwórz” prowadzi do linku", () => {
    renderRealtime();
    deliver({
      title: "Nowy request do pracy",
      link: "/jobs/13",
      notification_type: "request_assignment_changed",
      topic: "jobs",
      toast: true,
    });
    expect(showActionToast).toHaveBeenCalledTimes(1);
    const [text, options] = showActionToast.mock.calls[0];
    expect(text).toBe("Nowy request do pracy");
    options.onAction();
    expect(push).toHaveBeenCalledWith("/jobs/13");
  });

  it("ruch etapu zmienia tylko licznik — bez dymka", () => {
    renderRealtime();
    deliver({
      title: "CV wysłane: Marta Z.",
      link: "/jobs/5?candidate=9",
      notification_type: "stage_rule",
      topic: "jobs",
      toast: false,
    });
    expect(showActionToast).not.toHaveBeenCalled();
    expect(showInfo).not.toHaveBeenCalled();
  });

  it("bez dymka, gdy okienko tego tematu jest otwarte", () => {
    useRealtimeStatus.setState({ openTopic: "cv" });
    renderRealtime();
    deliver({ title: "CV gotowe do sprawdzenia: Ewa Lis", link: "/jobs/4", topic: "cv", toast: true });
    expect(showActionToast).not.toHaveBeenCalled();
  });

  it("reguła dymka: ramka bez tematu (stary backend) jak dawniej — z dymkiem", () => {
    expect(shouldToastFrame({}, null)).toBe(true);
    expect(shouldToastFrame({ topic: "other", toast: true }, "jobs")).toBe(true);
    expect(shouldToastFrame({ topic: "jobs", toast: true }, "jobs")).toBe(false);
    expect(shouldToastFrame({ topic: "cv", toast: false }, null)).toBe(false);
  });
});
