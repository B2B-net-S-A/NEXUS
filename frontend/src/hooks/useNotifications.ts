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
import {
  BOARD_TASKS_QUERY_KEY,
  CPRO_QUEUE_QUERY_KEY,
  CV_TOPIC_QUERY_KEY,
  DL_SEND_QUEUE_QUERY_KEY,
  type CvTopicResponse,
  type DlSendQueueResponse,
} from "@/lib/api/boardTasks";
import { pipelineCvRefresh } from "@/lib/pipeline-changed-refresh";
import { REQUEST_BOARD_QUERY_KEY } from "@/lib/api/requestAllocation";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import { interviewCycleQueryKey } from "@/lib/api/interviewCycle";
import {
  INTERVIEW_NOTIFY_EVENT,
  isInterviewNotificationType,
} from "@/lib/interview-notifications";
import {
  MY_PEOPLE_MATCH_FRAME,
  invalidateNotificationLists,
  isNoteNotificationType,
  type NotificationTopic,
} from "@/lib/notification-topics";

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
  /** Temat ikony paska (16.10.2026) — dokłada go serwer; starszy go nie wysyła. */
  topic?: NotificationTopic;
  /** Czy pokazać dymek — decyzja serwera (`notification_topics.TOAST_TYPES`). */
  toast?: boolean;
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
  CHAT_NOTIFY_EVENT,
  type CandidateChatBusEvent,
  type ChatBusEvent,
  type ChatNotifyEvent,
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
  /**
   * Użytkownik ma okienko „Rozmowy”: powiadomienia kategorii „Rozmowy” nie
   * podbijają licznika dzwonka ani nie wołają `onNotification`, tylko idą do
   * okienka jako zdarzenie okna (`INTERVIEW_NOTIFY_EVENT`).
   */
  interviewsInWindow?: boolean;
}

/** Okno zlewania odświeżeń dzwonka po wiadomościach czatu. */
export const CHAT_REFRESH_COALESCE_MS = 1_500;

/** `/jobs/42` albo `/jobs/42?tab=…` → 42; każdy inny link → `null`. */
export function jobIdFromLink(link: string | null | undefined): number | null {
  const match = /^\/jobs\/(\d+)(?:[/?#]|$)/.exec(link ?? "");
  if (!match) return null;
  const id = Number(match[1]);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

export function useNotifications({
  onNotification,
  interviewsInWindow = false,
}: UseNotificationsOptions = {}) {
  const { token, user } = useAuthStore();
  const queryClient = useQueryClient();
  // Konto czytane z refa z tego samego powodu co opcje niżej.
  const userRef = useRef(user);
  userRef.current = user;
  // Czytane z refa: zmiana opcji nie może przebudować `connect` i rozłączyć gniazda.
  const interviewsInWindowRef = useRef(interviewsInWindow);
  interviewsInWindowRef.current = interviewsInWindow;
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
        invalidateNotificationLists(queryClient, "messages");
        for (const key of keys) {
          queryClient.invalidateQueries({ queryKey: [key] });
        }
      }, CHAT_REFRESH_COALESCE_MS);
    },
    [queryClient],
  );

  // Timery debounce `pipeline_changed` — jeden na rekrutację — i Delivery
  // Leadzi z ramek sklejonych w to odświeżenie (`undefined` = ramka bez pola).
  const pipelineTimersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  const pipelineLeadsRef = useRef<Map<number, Set<number | null | undefined>>>(new Map());

  const schedulePipelineRefresh = useCallback(
    (jobId: number, deliveryLeadId: number | null | undefined) => {
      const timers = pipelineTimersRef.current;
      const pending = timers.get(jobId);
      if (pending) clearTimeout(pending);
      const leads = pipelineLeadsRef.current.get(jobId) ?? new Set();
      leads.add(deliveryLeadId);
      pipelineLeadsRef.current.set(jobId, leads);
      timers.set(
        jobId,
        setTimeout(() => {
          timers.delete(jobId);
          pipelineLeadsRef.current.delete(jobId);
          if (!mountedRef.current) return;
          // Tablica żyje pod dwoma kluczami (`String(id)` ze strony i `id`
          // z tablicy), a wyniki dopasowania w dwóch formach — stąd prefiks.
          queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
          queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
          queryClient.invalidateQueries({ queryKey: ["pipeline-scores", String(jobId)] });
          queryClient.invalidateQueries({ queryKey: ["pipeline-scores", jobId] });
          queryClient.invalidateQueries({ queryKey: ["my-next-steps"] });
          // Kolejka „Czeka na Ciebie" (DZ, Cpro) liczy się z ruchów na tablicach.
          // Sam klucz pulpitu i okna Cpro (pobierają się, tylko gdy są na
          // ekranie); ikona „CV” i `dl-send` z paska — tylko gdy ruch ich
          // dotyczy (27.10.2026, `lib/pipeline-changed-refresh.ts`).
          queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY, exact: true });
          queryClient.invalidateQueries({ queryKey: CPRO_QUEUE_QUERY_KEY });
          const refresh = pipelineCvRefresh(
            jobId,
            leads,
            userRef.current,
            queryClient.getQueryData<CvTopicResponse>(CV_TOPIC_QUERY_KEY),
            queryClient.getQueryData<DlSendQueueResponse>(DL_SEND_QUEUE_QUERY_KEY),
          );
          if (refresh.cv) queryClient.invalidateQueries({ queryKey: CV_TOPIC_QUERY_KEY });
          if (refresh.dlSend) {
            queryClient.invalidateQueries({ queryKey: DL_SEND_QUEUE_QUERY_KEY });
          }
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
  const visibleAgainRef = useRef<(() => void) | null>(null);
  const startPolling = useCallback(() => {
    if (pollingIntervalRef.current) return;
    pollingIntervalRef.current = setInterval(async () => {
      // Ukryta karta nie potrzebuje świeżych powiadomień — ręczny interwał
      // nie podlega `refetchIntervalInBackground`, więc pilnujemy tego sami.
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        return;
      }
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    }, NOTIFICATIONS_FALLBACK_POLL_MS);
    // Bez gniazda jedyną świeżością jest odpytywanie, a odświeżania przy
    // powrocie do karty nie ma od 27.10.2026 (`QueryProvider`) — powrót
    // odświeża listy sam, zamiast czekać do minuty na kolejny takt.
    if (typeof document !== "undefined") {
      const onVisible = () => {
        if (document.visibilityState === "visible") {
          queryClient.invalidateQueries({ queryKey: ["notifications"] });
        }
      };
      document.addEventListener("visibilitychange", onVisible);
      visibleAgainRef.current = onVisible;
    }
  }, [queryClient]);

  const stopPolling = useCallback(() => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
    if (visibleAgainRef.current) {
      document.removeEventListener("visibilitychange", visibleAgainRef.current);
      visibleAgainRef.current = null;
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

    // Nowa rekrutacja pasuje do „Moich ludzi" — licznik od razu, a Jarvis
    // dostaje sygnał do dymka „kogo przepiąć" (JarvisRoot nasłuchuje). Przychodzi
    // jako wiersz powiadomienia albo (od PR5, 16.10.2026) samo zdarzenie.
    const announceMyPeopleMatch = (title: string, link: string | null) => {
      queryClient.invalidateQueries({ queryKey: ["my-people"] });
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent<MyPeopleMatchEventDetail>(MY_PEOPLE_MATCH_EVENT, {
            detail: { title, link },
          }),
        );
      }
    };

    ws.onmessage = (event) => {
      if (!mountedRef.current) return;
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "notification" && msg.data) {
          const notif: WsNotification = msg.data;
          // Tylko lista tematu ramki (i listy spoza okienek) — nie cztery
          // okienka paska naraz (27.10.2026).
          invalidateNotificationLists(queryClient, notif.topic);
          if (notif.notification_type === "my_people_match") {
            announceMyPeopleMatch(notif.title, notif.link ?? null);
          }
          if (notif.notification_type === "request_allocation_proposals") {
            // Automat zaproponował osobę do requestu: Head of Recruitment ma
            // zobaczyć propozycję w „Czeka na Ciebie” i na pulpicie „Requesty
            // i obłożenie” od razu, nie po 5-minutowej siatce odpytywania.
            queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
            queryClient.invalidateQueries({ queryKey: REQUEST_BOARD_QUERY_KEY });
          } else if (
            notif.notification_type === "request_assignment_changed" ||
            // „Poprzedni rekruter” (14.10.2026): zespół zszedł z P1 / wrócił.
            notif.notification_type === "recruiter_parked" ||
            notif.notification_type === "recruiter_restored"
          ) {
            // Ktoś właśnie dostał request do pracy (akceptacja propozycji,
            // przydział automatu): zmienia się obsada rekrutacji, lista
            // „Moje”, jej liczniki i obłożenie na pulpicie — ten sam zestaw co
            // po zapisie z tego ekranu. Link po akceptacji to `/jobs/{id}`;
            // poranny zbiorczy wpis prowadzi na pulpit, więc odświeża każdą
            // wczytaną rekrutację.
            invalidateJobTeam(queryClient, jobIdFromLink(notif.link));
          }
          if (
            interviewsInWindowRef.current &&
            isInterviewNotificationType(notif.notification_type)
          ) {
            // Rozmowy u klienta i prepy mają własne okienko: dzwonek ich nie
            // liczy i nie pokazuje dymka. Powiadomienie przychodzi dokładnie
            // wtedy, gdy zmienia się stan cyklu, więc odświeżamy jego przegląd
            // (same zakresy — bez pytań klienta, debriefów i transkryptów
            // otwartych okien), a dymek pokazuje okienko „Rozmowy”.
            for (const scope of ["mine", "jobs", "all"] as const) {
              queryClient.invalidateQueries({
                queryKey: interviewCycleQueryKey(scope),
                exact: true,
              });
            }
            if (typeof window !== "undefined") {
              window.dispatchEvent(
                new CustomEvent<WsNotification>(INTERVIEW_NOTIFY_EVENT, { detail: notif }),
              );
            }
            return;
          }
          if (isNoteNotificationType(notif.notification_type)) {
            // Wzmianka i odpowiedź w notatce idą do okienka „Wiadomości”
            // (16.10.2026): lista odświeżyła się wyżej, dymek pokazuje okienko.
            if (typeof window !== "undefined") {
              window.dispatchEvent(
                new CustomEvent<ChatNotifyEvent>(CHAT_NOTIFY_EVENT, {
                  detail: {
                    kind: "note",
                    entity_id: 0,
                    notification_type: notif.notification_type,
                    link: notif.link ?? "",
                    thread_title: notif.title,
                    author_name: "",
                    preview: notif.message,
                  },
                }),
              );
            }
            return;
          }
          setUnreadCount((c) => c + 1);
          // Call external handler (for toast)
          onNotification?.(notif);
        } else if (msg.type === MY_PEOPLE_MATCH_FRAME && msg.data) {
          announceMyPeopleMatch(String(msg.data.title ?? ""), msg.data.link ?? null);
        } else if (msg.type === "pipeline_changed" && msg.data) {
          const jobId = Number(msg.data.job_id);
          if (Number.isSafeInteger(jobId) && jobId > 0) {
            const lead = msg.data.delivery_lead_id;
            schedulePipelineRefresh(
              jobId,
              lead === undefined ? undefined : Number.isSafeInteger(lead) ? lead : null,
            );
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
          invalidateNotificationLists(queryClient, "other");
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
        } else if (
          (msg.type === "chat:notify" || msg.type === "candidate-chat:notify") &&
          msg.data
        ) {
          // Zapowiedź powiadomienia czatu — także dla oznaczonej osoby spoza
          // zespołu, do której zdarzenia `…:message:new` nie docierają.
          scheduleChatRefresh([
            msg.type === "chat:notify" ? "job-chat-unread" : "candidate-chat-unread",
          ]);
          if (typeof window !== "undefined") {
            window.dispatchEvent(
              new CustomEvent<ChatNotifyEvent>(CHAT_NOTIFY_EVENT, {
                detail: msg.data as ChatNotifyEvent,
              }),
            );
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
    const pipelineLeads = pipelineLeadsRef.current;

    return () => {
      mountedRef.current = false;
      for (const timer of pipelineTimers.values()) clearTimeout(timer);
      pipelineTimers.clear();
      pipelineLeads.clear();
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
