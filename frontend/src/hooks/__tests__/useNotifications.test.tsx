import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/store/auth", () => ({
  useAuthStore: () => ({ token: "test-token" }),
}));

import {
  CHAT_REFRESH_COALESCE_MS,
  PIPELINE_CHANGED_DEBOUNCE_MS,
  jobIdFromLink,
  reconnectDelayMs,
  useNotifications,
} from "@/hooks/useNotifications";
import { NOTIFICATIONS_FALLBACK_POLL_MS } from "@/lib/polling";
import { CHAT_NOTIFY_EVENT } from "@/types/job-chat";

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

describe("useNotifications — zdarzenia czatu odświeżają dzwonek", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function flushChatRefresh() {
    act(() => {
      vi.advanceTimersByTime(CHAT_REFRESH_COALESCE_MS + 10);
    });
  }

  function deliver(message: unknown) {
    const ws = FakeWebSocket.instances[0];
    act(() => ws.onopen?.());
    act(() => ws.onmessage?.({ data: JSON.stringify(message) }));
  }

  it("nowa wiadomość w czacie rekrutacji unieważnia powiadomienia i licznik czatu", () => {
    const { hook, keys } = setup();
    deliver({ type: "chat:message:new", data: { id: 1, job_id: 7 } });
    flushChatRefresh();
    expect(keys()).toContain(JSON.stringify(["notifications"]));
    expect(keys()).toContain(JSON.stringify(["job-chat-unread"]));
    hook.unmount();
  });

  it("seria wiadomości daje JEDNO odświeżenie dzwonka, nie jedno na wiadomość", () => {
    const { hook, keys } = setup();
    const ws = FakeWebSocket.instances[0];
    act(() => ws.onopen?.());
    const before = keys().filter((k) => k === JSON.stringify(["notifications"])).length;
    for (let id = 1; id <= 5; id += 1) {
      act(() =>
        ws.onmessage?.({ data: JSON.stringify({ type: "chat:message:new", data: { id, job_id: 7 } }) }),
      );
    }
    expect(keys().filter((k) => k === JSON.stringify(["notifications"])).length).toBe(before);
    flushChatRefresh();
    expect(keys().filter((k) => k === JSON.stringify(["notifications"])).length).toBe(before + 1);
    hook.unmount();
  });

  it("nowa wiadomość w czacie kandydata unieważnia powiadomienia", () => {
    const { hook, keys } = setup();
    deliver({ type: "candidate-chat:message:new", data: { id: 2, candidate_id: 9 } });
    flushChatRefresh();
    expect(keys()).toContain(JSON.stringify(["notifications"]));
    expect(keys()).toContain(JSON.stringify(["candidate-chat-unread"]));
    hook.unmount();
  });

  it("zapowiedź powiadomienia czatu odświeża okienko i trafia do okna jako zdarzenie", () => {
    const { hook, keys } = setup();
    const seen: unknown[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(CHAT_NOTIFY_EVENT, listener);
    const detail = {
      kind: "job",
      entity_id: 7,
      notification_type: "job_chat_mention",
      link: "/jobs/7?tab=chat&msg=3",
      thread_title: "Tester automatyzujący",
      author_name: "Anna Przykładowa",
      preview: "Zerkniesz?",
    };
    deliver({ type: "chat:notify", data: detail });
    deliver({
      type: "candidate-chat:notify",
      data: { ...detail, kind: "candidate", link: "/candidates/9?tab=chat&msg=4" },
    });
    window.removeEventListener(CHAT_NOTIFY_EVENT, listener);

    expect(seen).toHaveLength(2);
    expect(seen[0]).toEqual(detail);
    flushChatRefresh();
    // Okienko „Czaty” żyje pod prefiksem `["notifications"]`.
    expect(keys()).toContain(JSON.stringify(["notifications"]));
    expect(keys()).toContain(JSON.stringify(["job-chat-unread"]));
    expect(keys()).toContain(JSON.stringify(["candidate-chat-unread"]));
    hook.unmount();
  });

  it("edycja wiadomości nie odpytuje dzwonka", () => {
    const { hook, keys } = setup();
    deliver({ type: "chat:message:edit", data: { id: 1, job_id: 7 } });
    deliver({ type: "candidate-chat:message:edit", data: { id: 2 } });
    flushChatRefresh();
    expect(keys()).not.toContain(JSON.stringify(["notifications"]));
    hook.unmount();
  });
});

describe("useNotifications — pipeline_changed (live kanban)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  function emit(ws: FakeWebSocket, payload: unknown) {
    act(() => ws.onmessage?.({ data: JSON.stringify(payload) }));
  }

  it("seria zdarzeń jednej rekrutacji odświeża tablicę raz, po oknie debounce", () => {
    const { hook, invalidate, keys } = setup();
    const ws = FakeWebSocket.instances[0];
    act(() => ws.onopen?.());

    emit(ws, { type: "pipeline_changed", data: { job_id: 42 } });
    act(() => {
      vi.advanceTimersByTime(PIPELINE_CHANGED_DEBOUNCE_MS / 2);
    });
    emit(ws, { type: "pipeline_changed", data: { job_id: 42 } });
    expect(keys()).toEqual([]);

    act(() => {
      vi.advanceTimersByTime(PIPELINE_CHANGED_DEBOUNCE_MS);
    });
    expect(keys()).toEqual([
      JSON.stringify(["kanban", "42"]),
      JSON.stringify(["kanban", 42]),
      JSON.stringify(["pipeline-scores", "42"]),
      JSON.stringify(["pipeline-scores", 42]),
      JSON.stringify(["my-next-steps"]),
      // Kolejka „Czeka na Ciebie" (DZ, Cpro) na pulpicie.
      JSON.stringify(["board-tasks"]),
      // „Moi ludzie": lista i zakładka rekrutacji (bez podsumowania awatara).
      JSON.stringify(["my-people", "list"]),
      JSON.stringify(["my-people", "for-job"]),
    ]);
    expect(invalidate).toHaveBeenCalledTimes(8);
    hook.unmount();
  });

  it("różne rekrutacje mają osobne okna, a śmieciowe job_id nic nie robią", () => {
    const { hook, keys } = setup();
    const ws = FakeWebSocket.instances[0];
    act(() => ws.onopen?.());

    emit(ws, { type: "pipeline_changed", data: { job_id: 1 } });
    emit(ws, { type: "pipeline_changed", data: { job_id: 2 } });
    emit(ws, { type: "pipeline_changed", data: { job_id: "abc" } });
    act(() => {
      vi.advanceTimersByTime(PIPELINE_CHANGED_DEBOUNCE_MS);
    });
    expect(keys()).toContain(JSON.stringify(["kanban", 1]));
    expect(keys()).toContain(JSON.stringify(["kanban", 2]));
    expect(keys().filter((k) => k.startsWith('["kanban"'))).toHaveLength(4);
    hook.unmount();
  });

  it("odmontowanie przed końcem okna nie odświeża niczego", () => {
    const { hook, keys } = setup();
    const ws = FakeWebSocket.instances[0];
    act(() => ws.onopen?.());
    emit(ws, { type: "pipeline_changed", data: { job_id: 7 } });
    hook.unmount();
    act(() => {
      vi.advanceTimersByTime(PIPELINE_CHANGED_DEBOUNCE_MS * 2);
    });
    expect(keys()).toEqual([]);
  });
});

describe("useNotifications — przydział requestów (propozycje automatu i akceptacja)", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function deliver(data: Record<string, unknown>) {
    const ws = FakeWebSocket.instances[0];
    act(() => ws.onopen?.());
    act(() =>
      ws.onmessage?.({
        data: JSON.stringify({
          type: "notification",
          data: { id: 1, title: "t", message: "m", created_at: "2026-10-02T08:00:00Z", ...data },
        }),
      }),
    );
  }

  it("nowa propozycja automatu odświeża „Czeka na Ciebie” i pulpit „Requesty i obłożenie”", () => {
    const { hook, keys } = setup();
    deliver({ notification_type: "request_allocation_proposals", link: "/dashboard#czeka-na-ciebie" });
    expect(keys()).toEqual([
      JSON.stringify(["notifications"]),
      JSON.stringify(["board-tasks"]),
      JSON.stringify(["request-board"]),
    ]);
    hook.unmount();
  });

  it("przydzielony request odświeża rekrutację, listę „Moje” z licznikami, pulpit i zadania", () => {
    const { hook, keys } = setup();
    deliver({ notification_type: "request_assignment_changed", link: "/jobs/42" });
    expect(keys()).toEqual([
      JSON.stringify(["notifications"]),
      // Rekrutacja żyje pod dwoma kluczami (liczba i napis z adresu).
      JSON.stringify(["job", 42]),
      JSON.stringify(["job", "42"]),
      JSON.stringify(["jobs-v2"]),
      JSON.stringify(["jobs-quick-counts"]),
      JSON.stringify(["request-board"]),
      JSON.stringify(["board-tasks"]),
    ]);
    hook.unmount();
  });

  it("poranny zbiorczy wpis (link na pulpit) odświeża każdą wczytaną rekrutację", () => {
    const { hook, keys } = setup();
    deliver({ notification_type: "request_assignment_changed", link: "/dashboard" });
    expect(keys()).toContain(JSON.stringify(["job"]));
    expect(keys()).toContain(JSON.stringify(["jobs-v2"]));
    expect(keys()).toContain(JSON.stringify(["request-board"]));
    hook.unmount();
  });

  it("inne powiadomienie odświeża tylko dzwonek", () => {
    const { hook, keys } = setup();
    deliver({ notification_type: "stage_changed", link: "/jobs/42" });
    expect(keys()).toEqual([JSON.stringify(["notifications"])]);
    hook.unmount();
  });
});

describe("jobIdFromLink", () => {
  it("czyta id rekrutacji tylko z linku do rekrutacji", () => {
    expect(jobIdFromLink("/jobs/42")).toBe(42);
    expect(jobIdFromLink("/jobs/42?tab=champion")).toBe(42);
    expect(jobIdFromLink("/jobs/42/")).toBe(42);
    expect(jobIdFromLink("/jobs/review-states")).toBeNull();
    expect(jobIdFromLink("/jobs/0")).toBeNull();
    expect(jobIdFromLink("/dashboard#czeka-na-ciebie")).toBeNull();
    expect(jobIdFromLink("/candidates/42")).toBeNull();
    expect(jobIdFromLink(undefined)).toBeNull();
    expect(jobIdFromLink(null)).toBeNull();
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
