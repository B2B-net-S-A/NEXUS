"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { NOTIFICATIONS_FALLBACK_POLL_MS } from "@/lib/polling";
import { useAuthStore } from "@/store/auth";
import { useQueryClient } from "@tanstack/react-query";
import {
  PRESENCE_EVENT,
  WS_OPEN_EVENT,
  activePresenceKeys,
  clearWsSender,
  setWsSender,
} from "@/lib/wsBus";
import { MY_PEOPLE_MATCH_EVENT, type MyPeopleMatchEventDetail } from "@/lib/my-people-summary";

const WS_BASE =
  (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")
    .replace(/^http/, "ws")
    .replace(/^https/, "wss");

export interface WsNotification {
  id: number;
  title: string;
  message: string;
  link?: string;
  /** Typ z serwera (`notification_triggers.emit`) — steruje unieważnianiem cache. */
  notification_type?: string;
  created_at: string;
}

export interface ChampionProfileChangedEventDetail {
  job_id: number;
  updated_by_user_id: number;
  updated_by_name: string;
  updated_at: string;
  fields_changed: string[];
}

// Event name used to broadcast champion-profile live refresh signals from
// the WS hook to any mounted editor. Components listen via
// `window.addEventListener('nexus:cp-changed', ...)` so the hook stays
// decoupled from editor internals.
export const CHAMPION_PROFILE_CHANGED_EVENT = "nexus:cp-changed";

// Event name for KPI Coach nudges (praise / remind / eod_summary).
// `KpiNudgeToaster` listens and renders the in-app toast. Keeping the
// constant in sync with frontend/src/components/v2/kpi/KpiNudgeToaster.tsx.
export const KPI_NUDGE_EVENT = "nexus:kpi-nudge";

// Job + Candidate Chat events — re-broadcast z WS do *ChatTab. Komponent
// listenuje odpowiedni event bus i sam invaliduje React Query keys.
import {
  CANDIDATE_CHAT_BUS_EVENT,
  CHAT_BUS_EVENT,
  type CandidateChatBusEvent,
  type ChatBusEvent,
} from "@/types/job-chat";

/** Ruch zespołu na tablicy rekrutacji przychodzi jako `pipeline_changed`.
 *  Ruch zbiorczy potrafi wysłać serię zdarzeń tej samej rekrutacji w ciągu
 *  ułamka sekundy — okno skleja je w jedno odświeżenie tablicy. To nie jest
 *  interwał odpytywania (stąd poza `lib/polling.ts`). */
export const PIPELINE_CHANGED_DEBOUNCE_MS = 1_000;

/** Wykładniczy backoff ponownego łączenia (sufit 30 s) z rozrzutem 50–100%. */
export function reconnectDelayMs(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(1000 * Math.pow(2, attempt), 30_000);
  return Math.round(base * (0.5 + random() * 0.5));
}

interface UseNotificationsOptions {
  onNotification?: (notif: WsNotification) => void;
}

/** Okno zlewania odświeżeń dzwonka po wiadomościach czatu. */
export const CHAT_REFRESH_COALESCE_MS = 1_500;

export function useNotifications({ onNotification }: UseNotificationsOptions = {}) {
  const { token } = useAuthStore();
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const mountedRef = useRef(true);
  const pollingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Czy to połączenie jest POWROTEM po zerwaniu (a nie pierwszym otwarciem).
  const lostConnectionRef = useRef(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  // Każda wiadomość czatu tworzy powiadomienie dla KAŻDEGO członka zespołu,
  // więc dzwonek musi się odświeżyć — ale w żywej rozmowie seria wiadomości
  // dawałaby serię refetchy u wszystkich. Zlewamy je w jedno odświeżenie po
  // krótkiej ciszy (przegląd 17.09.2026).
  const chatRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chatRefreshKeysRef = useRef<Set<string>>(new Set());
  const scheduleChatRefresh = useCallback(
    (unreadKey: [string]) => {
      chatRefreshKeysRef.current.add(unreadKey[0]);
      if (chatRefreshTimerRef.current) return;
      chatRefreshTimerRef.current = setTimeout(() => {
        chatRefreshTimerRef.current = null;
        const keys = Array.from(chatRefreshKeysRef.current);
        chatRefreshKeysRef.current.clear();
        queryClient.invalidateQueries({ queryKey: ["notifications"] });
        for (const key of keys) {
          queryClient.invalidateQueries({ queryKey: [key] });
        }
      }, CHAT_REFRESH_COALESCE_MS);
    },
    [queryClient],
  );

  // Timery debounce `pipeline_changed` — jeden na rekrutację.
  const pipelineTimersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const schedulePipelineRefresh = useCallback(
    (jobId: number) => {
      const timers = pipelineTimersRef.current;
      const pending = timers.get(jobId);
      if (pending) clearTimeout(pending);
      timers.set(
        jobId,
        setTimeout(() => {
          timers.delete(jobId);
          if (!mountedRef.current) return;
          // Tablica żyje pod dwoma kluczami (`String(id)` ze strony i `id`
          // z tablicy), a wyniki dopasowania w dwóch formach — stąd prefiks.
          queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
          queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
          queryClient.invalidateQueries({ queryKey: ["pipeline-scores", String(jobId)] });
          queryClient.invalidateQueries({ queryKey: ["pipeline-scores", jobId] });
          queryClient.invalidateQueries({ queryKey: ["my-next-steps"] });
          // Kolejka „Czeka na Ciebie" (DZ, Cpro) liczy się z ruchów na tablicach.
          queryClient.invalidateQueries({ queryKey: ["board-tasks"] });
          // „Moi ludzie": lista i zakładka rekrutacji zależą od ruchów na
          // tablicy (kto jest w procesie, kto już w tej rekrutacji). Podsumowania
          // awatara NIE ruszamy — liczy całą listę, a ruchy go nie zmieniają.
          queryClient.invalidateQueries({ queryKey: ["my-people", "list"] });
          queryClient.invalidateQueries({ queryKey: ["my-people", "for-job"] });
        }, PIPELINE_CHANGED_DEBOUNCE_MS),
      );
    },
    [queryClient],
  );

  // Poll fallback when WS is unavailable
  const startPolling = useCallback(() => {
    if (pollingIntervalRef.current) return;
    pollingIntervalRef.current = setInterval(async () => {
      // Ukryta karta nie potrzebuje świeżych powiadomień — ręczny interwał
      // nie podlega `refetchIntervalInBackground`, więc pilnujemy tego sami.
      // Po powrocie do karty react-query odświeża przy focusie.
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        return;
      }
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    }, NOTIFICATIONS_FALLBACK_POLL_MS);
  }, [queryClient]);

  const stopPolling = useCallback(() => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!token || !mountedRef.current) return;

    // Clean up existing connection
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    // Carry the JWT on the WS subprotocol instead of the query string so it
    // never lands in access/proxy/trace logs (P1-WS-01). The server reads the
    // token from the second offered subprotocol and echoes the "access_token"
    // sentinel back as the negotiated subprotocol.
    const url = `${WS_BASE}/ws/notifications`;
    let ws: WebSocket;

    try {
      ws = new WebSocket(url, ["access_token", token]);
    } catch {
      // WebSocket not supported or URL invalid — fall back to polling
      startPolling();
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      reconnectAttemptsRef.current = 0;
      setWsConnected(true);
      stopPolling(); // WS is up — no need to poll

      // Powrót po zerwaniu: serwer nie odtwarza zdarzeń z przerwy (wysyła
      // tylko `connected`), a dzwonek przy zdrowym gnieździe odpytuje co 5 min.
      // Jeden odczyt po odzyskaniu połączenia zamiast czekania na siatkę
      // bezpieczeństwa (reaudyt 14.09.2026, R02). Pierwsze otwarcie nie
      // odświeża — komponenty i tak właśnie pobrały dane.
      if (lostConnectionRef.current) {
        lostConnectionRef.current = false;
        queryClient.invalidateQueries({ queryKey: ["notifications"] });
        queryClient.invalidateQueries({ queryKey: ["kpis", "me", "today"] });
      }

      // Expose a sender to `usePresence` without it needing the ws ref.
      setWsSender((msg) => ws.send(JSON.stringify(msg)));

      // Replay any presence subscriptions that were active before reconnect.
      for (const key of activePresenceKeys) {
        const [resource_type, rid] = key.split(":");
        const resource_id = Number(rid);
        if (!resource_type || Number.isNaN(resource_id)) continue;
        try {
          ws.send(
            JSON.stringify({
              type: "presence:subscribe",
              resource_type,
              resource_id,
            }),
          );
        } catch {
          // ignore; reconnect loop will retry
        }
      }

      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent(WS_OPEN_EVENT));
      }
    };

    ws.onmessage = (event) => {
      if (!mountedRef.current) return;
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "notification" && msg.data) {
          const notif: WsNotification = msg.data;
          // Update react-query cache
          queryClient.invalidateQueries({ queryKey: ["notifications"] });
          if (notif.notification_type === "my_people_match") {
            // Nowa rekrutacja pasuje do „Moich ludzi" — licznik od razu, a Jarvis
            // dostaje sygnał do dymka „kogo przepiąć" (JarvisRoot nasłuchuje).
            queryClient.invalidateQueries({ queryKey: ["my-people"] });
            if (typeof window !== "undefined") {
              window.dispatchEvent(
                new CustomEvent<MyPeopleMatchEventDetail>(MY_PEOPLE_MATCH_EVENT, {
                  detail: { title: notif.title, link: notif.link ?? null },
                }),
              );
            }
          }
          setUnreadCount((c) => c + 1);
          // Call external handler (for toast)
          onNotification?.(notif);
        } else if (msg.type === "pipeline_changed" && msg.data) {
          const jobId = Number(msg.data.job_id);
          if (Number.isSafeInteger(jobId) && jobId > 0) {
            schedulePipelineRefresh(jobId);
          }
        } else if (msg.type === "champion_profile_changed" && msg.data) {
          // Re-broadcast to any mounted CP editor. The editor decides
          // whether the event is relevant (matching job_id, different
          // editor user id) and invalidates its own React Query key.
          if (typeof window !== "undefined") {
            window.dispatchEvent(
              new CustomEvent<ChampionProfileChangedEventDetail>(
                CHAMPION_PROFILE_CHANGED_EVENT,
                { detail: msg.data },
              ),
            );
          }
        } else if (msg.type === "kpi_nudge" && msg.data) {
          // KPI Coach: update cached KPI snapshot + bell counter, then
          // broadcast to the KpiNudgeToaster for the in-app toast.
          queryClient.invalidateQueries({ queryKey: ["kpis", "me", "today"] });
          queryClient.invalidateQueries({ queryKey: ["notifications"] });
          setUnreadCount((c) => c + 1);
          if (typeof window !== "undefined") {
            window.dispatchEvent(
              new CustomEvent(KPI_NUDGE_EVENT, { detail: msg.data }),
            );
          }
        } else if (msg.type === "chat:message:new" && msg.data) {
          // Wzmianka `@Ty` w czacie tworzy powiadomienie po stronie serwera, ale
          // gniazdo niesie wyłącznie zdarzenie czatu — bez tego dzwonek i licznik
          // nieprzeczytanych czatu czekały na 5-minutowy poll.
          scheduleChatRefresh(["job-chat-unread"]);
          if (typeof window !== "undefined") {
            const detail: ChatBusEvent = { kind: "new", data: msg.data };
            window.dispatchEvent(
              new CustomEvent<ChatBusEvent>(CHAT_BUS_EVENT, { detail }),
            );
          }
        } else if (msg.type === "chat:message:edit" && msg.data) {
          if (typeof window !== "undefined") {
            const detail: ChatBusEvent = { kind: "edit", data: msg.data };
            window.dispatchEvent(
              new CustomEvent<ChatBusEvent>(CHAT_BUS_EVENT, { detail }),
            );
          }
        } else if (msg.type === "chat:message:delete" && msg.data) {
          if (typeof window !== "undefined") {
            const detail: ChatBusEvent = { kind: "delete", data: msg.data };
            window.dispatchEvent(
              new CustomEvent<ChatBusEvent>(CHAT_BUS_EVENT, { detail }),
            );
          }
        } else if (msg.type === "chat:message:pin" && msg.data) {
          if (typeof window !== "undefined") {
            const detail: ChatBusEvent = { kind: "pin", data: msg.data };
            window.dispatchEvent(
              new CustomEvent<ChatBusEvent>(CHAT_BUS_EVENT, { detail }),
            );
          }
        } else if (msg.type === "chat:message:reaction" && msg.data) {
          if (typeof window !== "undefined") {
            const detail: ChatBusEvent = { kind: "reaction", data: msg.data };
            window.dispatchEvent(
              new CustomEvent<ChatBusEvent>(CHAT_BUS_EVENT, { detail }),
            );
          }
        } else if (
          typeof msg.type === "string" &&
          msg.type.startsWith("candidate-chat:message:") &&
          msg.data
        ) {
          if (msg.type === "candidate-chat:message:new") {
            // Jak w czacie rekrutacji: wzmianka ma trafić do dzwonka na żywo.
            scheduleChatRefresh(["candidate-chat-unread"]);
          }
          if (typeof window !== "undefined") {
            const kindMap: Record<string, CandidateChatBusEvent["kind"]> = {
              "candidate-chat:message:new": "new",
              "candidate-chat:message:edit": "edit",
              "candidate-chat:message:delete": "delete",
              "candidate-chat:message:pin": "pin",
              "candidate-chat:message:reaction": "reaction",
            };
            const kind = kindMap[msg.type];
            if (kind) {
              const detail = { kind, data: msg.data } as CandidateChatBusEvent;
              window.dispatchEvent(
                new CustomEvent<CandidateChatBusEvent>(
                  CANDIDATE_CHAT_BUS_EVENT,
                  { detail },
                ),
              );
            }
          }
        } else if (msg.type === "ping") {
          ws.send("ping");
        } else if (
          typeof msg.type === "string" &&
          msg.type.startsWith("presence:")
        ) {
          if (typeof window !== "undefined") {
            window.dispatchEvent(new CustomEvent(PRESENCE_EVENT, { detail: msg }));
          }
        }
      } catch {
        // ignore malformed messages
      }
    };

    ws.onerror = () => {
      // Will trigger onclose
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setWsConnected(false);
      wsRef.current = null;
      lostConnectionRef.current = true;
      clearWsSender();

      // Start polling as fallback
      startPolling();

      // Exponential backoff reconnect: 1s, 2s, 4s, 8s, 16s, max 30s — z losowym
      // rozrzutem 50–100%. Po deployu gniazda zrywają się wszystkim naraz;
      // stałe opóźnienia wracały jedną falą 100 połączeń w tej samej sekundzie.
      const delay = reconnectDelayMs(reconnectAttemptsRef.current);
      reconnectAttemptsRef.current += 1;

      reconnectTimeoutRef.current = setTimeout(() => {
        if (mountedRef.current) {
          connect();
        }
      }, delay);
    };
  }, [
    token,
    queryClient,
    onNotification,
    startPolling,
    stopPolling,
    scheduleChatRefresh,
    schedulePipelineRefresh,
  ]);

  // Reset unread badge when user opens notification dropdown
  const clearUnread = useCallback(() => {
    setUnreadCount(0);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    const pipelineTimers = pipelineTimersRef.current;

    return () => {
      mountedRef.current = false;
      for (const timer of pipelineTimers.values()) clearTimeout(timer);
      pipelineTimers.clear();
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (chatRefreshTimerRef.current) {
        clearTimeout(chatRefreshTimerRef.current);
        chatRefreshTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
      stopPolling();
    };
  }, [connect, stopPolling]);

  return { wsConnected, unreadCount, clearUnread };
}
