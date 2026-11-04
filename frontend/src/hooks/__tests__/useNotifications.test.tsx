import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authState = vi.hoisted(() => ({
  token: "test-token",
  user: null as null | { id: number; role: string; roles: string[] },
}));

vi.mock("@/store/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/store/auth")>()),
  useAuthStore: () => authState,
}));

import {
  CHAT_REFRESH_COALESCE_MS,
  PIPELINE_CHANGED_DEBOUNCE_MS,
  jobIdFromLink,
  reconnectDelayMs,
  useNotifications,
} from "@/hooks/useNotifications";
import { NOTIFICATIONS_FALLBACK_POLL_MS } from "@/lib/polling";
import { INTERVIEW_NOTIFY_EVENT } from "@/lib/interview-notifications";
import { CHAT_NOTIFY_EVENT } from "@/types/job-chat";
import { MY_PEOPLE_MATCH_EVENT } from "@/lib/my-people-summary";

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

function setup(options: Parameters<typeof useNotifications>[0] = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook((props: Parameters<typeof useNotifications>[0]) => useNotifications(props), {
    wrapper,
    initialProps: options,
  });
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
    // Ruchy kolegów z czasu przerwy — Tablica nie odświeża się przy focusie.
    expect(keys()).toContain(JSON.stringify(["kanban"]));
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
      // Kolejka „Czeka na Ciebie" (DZ, Cpro) na pulpicie i okno Cpro.
      JSON.stringify(["board-tasks"]),
      JSON.stringify(["board-tasks", "cpro", "queue"]),
      // Bez konta w pamięci — ikona „CV” i `dl-send` jak dawniej.
      JSON.stringify(["board-tasks", "cv"]),
      JSON.stringify(["board-tasks", "dl-send"]),
      // „Moi ludzie": lista i zakładka rekrutacji (bez podsumowania awatara).
      JSON.stringify(["my-people", "list"]),
      JSON.stringify(["my-people", "for-job"]),
    ]);
    expect(invalidate).toHaveBeenCalledTimes(11);
    // Pulpit tylko pod swoim kluczem, nie cały prefiks `["board-tasks"]`.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["board-tasks"], exact: true });
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

// 13.10.2026: rozmowy u klienta i prepy mają własne okienko w górnym pasku.
describe("useNotifications — kategoria „Rozmowy” idzie do własnego okienka", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  const SLOTS = {
    type: "notification",
    data: {
      id: 9,
      title: "Terminy rozmowy od klienta",
      message: "3 terminy",
      link: "/calendar?cycle=1-2",
      notification_type: "interview_slots_requested",
      created_at: "2026-10-13T08:00:00Z",
    },
  };

  function deliver(payload: unknown) {
    const ws = FakeWebSocket.instances[0];
    act(() => ws.onopen?.());
    act(() => ws.onmessage?.({ data: JSON.stringify(payload) }));
  }

  it("z okienkiem: bez licznika i dymka dzwonka, przegląd cyklu odświeżony, zdarzenie okna", () => {
    const onNotification = vi.fn();
    const received: unknown[] = [];
    const listener = (event: Event) => received.push((event as CustomEvent).detail);
    window.addEventListener(INTERVIEW_NOTIFY_EVENT, listener);
    const { hook, invalidate } = setup({ onNotification, interviewsInWindow: true });

    deliver(SLOTS);

    expect(hook.result.current.unreadCount).toBe(0);
    expect(onNotification).not.toHaveBeenCalled();
    expect(received).toEqual([SLOTS.data]);
    // Same zakresy przeglądu, dokładnie — bez pytań klienta, debriefów
    // i transkryptów otwartych okien pod wspólnym prefiksem.
    expect(invalidate.mock.calls.map((call) => call[0])).toEqual([
      { queryKey: ["notifications"] },
      { queryKey: ["interview-cycle", "mine"], exact: true },
      { queryKey: ["interview-cycle", "jobs"], exact: true },
      { queryKey: ["interview-cycle", "all"], exact: true },
    ]);
    window.removeEventListener(INTERVIEW_NOTIFY_EVENT, listener);
    hook.unmount();
  });

  it("bez okienka rozmowy zostają w dzwonku, a inne typy zawsze", () => {
    const onNotification = vi.fn();
    const { hook, keys } = setup({ onNotification });
    deliver(SLOTS);
    expect(hook.result.current.unreadCount).toBe(1);
    expect(onNotification).toHaveBeenCalledTimes(1);
    expect(keys()).toEqual([JSON.stringify(["notifications"])]);
    hook.unmount();

    FakeWebSocket.instances = [];
    const other = setup({ onNotification, interviewsInWindow: true });
    deliver({ ...SLOTS, data: { ...SLOTS.data, notification_type: "stage_changed" } });
    expect(other.hook.result.current.unreadCount).toBe(1);
    expect(onNotification).toHaveBeenCalledTimes(2);
    other.hook.unmount();
  });

  it("zmiana opcji nie rozłącza gniazda", () => {
    const onNotification = vi.fn();
    const { hook } = setup({ onNotification, interviewsInWindow: false });
    expect(FakeWebSocket.instances).toHaveLength(1);

    hook.rerender({ onNotification, interviewsInWindow: true });

    expect(FakeWebSocket.instances).toHaveLength(1);
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

describe("useNotifications — ikony paska zamiast dzwonka (16.10.2026)", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function frame(payload: unknown) {
    const ws = FakeWebSocket.instances[0];
    act(() => ws.onopen?.());
    act(() => ws.onmessage?.({ data: JSON.stringify(payload) }));
  }

  it("wzmianka w notatce idzie do „Wiadomości”, bez licznika i dymka dzwonka", () => {
    const onNotification = vi.fn();
    const seen: unknown[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(CHAT_NOTIFY_EVENT, listener);
    const { hook, keys } = setup({ onNotification });
    frame({
      type: "notification",
      data: {
        id: 9,
        title: "Kasia W. oznaczył(a) Cię w notatce",
        message: "@Piotr sprawdź stawkę",
        link: "/candidates/3?tab=activity&activity=notes&note=11",
        notification_type: "note_mention",
        created_at: "2026-10-16T08:00:00Z",
        topic: "messages",
        toast: true,
      },
    });
    window.removeEventListener(CHAT_NOTIFY_EVENT, listener);

    expect(keys()).toEqual([JSON.stringify(["notifications"])]);
    expect(onNotification).not.toHaveBeenCalled();
    expect(hook.result.current.unreadCount).toBe(0);
    expect(seen).toEqual([
      {
        kind: "note",
        entity_id: 0,
        notification_type: "note_mention",
        link: "/candidates/3?tab=activity&activity=notes&note=11",
        thread_title: "Kasia W. oznaczył(a) Cię w notatce",
        author_name: "",
        preview: "@Piotr sprawdź stawkę",
      },
    ]);
    hook.unmount();
  });

  it("zdarzenie „Moich ludzi” bez wiersza odświeża listę i budzi Jarvisa", () => {
    const seen: unknown[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(MY_PEOPLE_MATCH_EVENT, listener);
    const onNotification = vi.fn();
    const { hook, keys } = setup({ onNotification });
    frame({
      type: "my_people:match",
      data: { title: "Nowa rekrutacja: Analityk — 3 z Twoich ludzi pasuje", link: "/jobs/4?people=1" },
    });
    window.removeEventListener(MY_PEOPLE_MATCH_EVENT, listener);

    expect(keys()).toEqual([JSON.stringify(["my-people"])]);
    expect(seen).toEqual([
      { title: "Nowa rekrutacja: Analityk — 3 z Twoich ludzi pasuje", link: "/jobs/4?people=1" },
    ]);
    // Bez wiersza nie ma czego liczyć ani pokazywać jako powiadomienia.
    expect(onNotification).not.toHaveBeenCalled();
    hook.unmount();
  });
});

// 27.10.2026: mniej żądań z przeglądarek — ramka odświeża listę swojego
// tematu, ruch karty odświeża „CV” i `dl-send` tylko tam, gdzie dotyczy.
describe("useNotifications — odświeżenia tylko tam, gdzie zdarzenie dotyczy", () => {
  const LISTS = {
    chats: ["notifications", "u1", "chats"],
    interviews: ["notifications", "u1", "interviews"],
    jobs: ["notifications", "u1", "jobs"],
    contracts: ["notifications", "u1", "contracts"],
    dashboard: ["notifications", "u1", 20],
  } as const;

  function setupReal() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    for (const key of Object.values(LISTS)) client.setQueryData([...key], { seeded: true });
    client.setQueryData(["board-tasks"], { seeded: true });
    client.setQueryData(["board-tasks", "cv"], {
      badge: 1,
      recruiter: {
        to_check: [],
        to_fix: [],
        with_dl: [{ job_id: 42, stage_id: 1, candidate_id: 1 }],
        sent: [],
      },
      dl: null,
    });
    client.setQueryData(["board-tasks", "dl-send"], { ready: [], ready_total: 0 });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const hook = renderHook(() => useNotifications(), { wrapper });
    const ws = FakeWebSocket.instances[0];
    act(() => ws.onopen?.());
    const stale = () =>
      Object.entries(LISTS)
        .filter(([, key]) => client.getQueryState([...key])?.isInvalidated)
        .map(([name]) => name);
    const invalidated = (key: unknown[]) => Boolean(client.getQueryState(key)?.isInvalidated);
    const send = (payload: unknown) =>
      act(() => ws.onmessage?.({ data: JSON.stringify(payload) }));
    return { hook, stale, invalidated, send };
  }

  function frame(topic?: string) {
    return {
      type: "notification",
      data: {
        id: 1,
        title: "t",
        message: "m",
        created_at: "2026-10-27T08:00:00Z",
        notification_type: "stage_changed",
        ...(topic ? { topic } : {}),
      },
    };
  }

  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    authState.user = null;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  });

  it("ramka tematu „Rekrutacje” odświeża jego okienko i pulpit, nie pozostałe trzy", () => {
    const { hook, stale, send } = setupReal();
    send(frame("jobs"));
    expect(stale()).toEqual(["jobs", "dashboard"]);
    hook.unmount();
  });

  it("temat bez okienka (`cv`, `other`) nie odświeża żadnego okienka paska", () => {
    const { hook, stale, send } = setupReal();
    send(frame("other"));
    expect(stale()).toEqual(["dashboard"]);
    hook.unmount();
  });

  it("ramka bez tematu (stary backend) odświeża wszystko, jak dawniej", () => {
    const { hook, stale, send } = setupReal();
    send(frame());
    expect(stale()).toEqual(["chats", "interviews", "jobs", "contracts", "dashboard"]);
    hook.unmount();
  });

  it("wiadomość czatu odświeża „Wiadomości”, nie „Rekrutacje”, „Rozmowy” i „Umowy”", () => {
    const { hook, stale, send } = setupReal();
    send({ type: "chat:message:new", data: { id: 1, job_id: 7 } });
    act(() => {
      vi.advanceTimersByTime(CHAT_REFRESH_COALESCE_MS + 10);
    });
    expect(stale()).toEqual(["chats", "dashboard"]);
    hook.unmount();
  });

  it("ruch karty u rekrutera: „CV” tylko z wierszem tej rekrutacji, `dl-send` wcale", () => {
    authState.user = { id: 5, role: "recruiter", roles: ["recruiter"] };
    const { hook, invalidated, send } = setupReal();
    send({ type: "pipeline_changed", data: { job_id: 99, delivery_lead_id: 8 } });
    act(() => {
      vi.advanceTimersByTime(PIPELINE_CHANGED_DEBOUNCE_MS);
    });
    expect(invalidated(["board-tasks", "cv"])).toBe(false);
    expect(invalidated(["board-tasks", "dl-send"])).toBe(false);
    // Pulpit „Czeka na Ciebie” dalej świeży.
    expect(invalidated(["board-tasks"])).toBe(true);

    send({ type: "pipeline_changed", data: { job_id: 42, delivery_lead_id: 8 } });
    act(() => {
      vi.advanceTimersByTime(PIPELINE_CHANGED_DEBOUNCE_MS);
    });
    expect(invalidated(["board-tasks", "cv"])).toBe(true);
    expect(invalidated(["board-tasks", "dl-send"])).toBe(false);
    hook.unmount();
  });

  it("ruch karty u Delivery Leada tej rekrutacji odświeża „CV” i `dl-send`", () => {
    authState.user = { id: 8, role: "delivery_lead", roles: ["delivery_lead"] };
    const { hook, invalidated, send } = setupReal();
    send({ type: "pipeline_changed", data: { job_id: 99, delivery_lead_id: 8 } });
    act(() => {
      vi.advanceTimersByTime(PIPELINE_CHANGED_DEBOUNCE_MS);
    });
    expect(invalidated(["board-tasks", "cv"])).toBe(true);
    expect(invalidated(["board-tasks", "dl-send"])).toBe(true);
    hook.unmount();
  });

  it("bez gniazda powrót do karty odświeża listy od razu, nie po takcie odpytywania", () => {
    const { hook, stale } = setupReal();
    const ws = FakeWebSocket.instances[0];
    vi.stubGlobal(
      "WebSocket",
      class {
        constructor() {
          throw new Error("offline");
        }
      },
    );
    act(() => ws.onclose?.());
    expect(stale()).toEqual([]);
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(stale()).toEqual(["chats", "interviews", "jobs", "contracts", "dashboard"]);
    hook.unmount();
  });
});
