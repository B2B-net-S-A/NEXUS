"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useAuthStore } from "@/store/auth";
import { useQueryClient } from "@tanstack/react-query";
import {
  PRESENCE_EVENT,
  WS_OPEN_EVENT,
  activePresenceKeys,
  clearWsSender,
  setWsSender,
} from "@/lib/wsBus";

const WS_BASE =
  (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")
    .replace(/^http/, "ws")
    .replace(/^https/, "wss");

export interface WsNotification {
  id: number;
  title: string;
  message: string;
  link?: string;
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

interface UseNotificationsOptions {
  onNotification?: (notif: WsNotification) => void;
}

export function useNotifications({ onNotification }: UseNotificationsOptions = {}) {
  const { token } = useAuthStore();
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const mountedRef = useRef(true);
  const pollingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);

  // Poll fallback when WS is unavailable
  const startPolling = useCallback(() => {
    if (pollingIntervalRef.current) return;
    pollingIntervalRef.current = setInterval(async () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    }, 30_000);
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

    const url = `${WS_BASE}/ws/notifications?token=${encodeURIComponent(token)}`;
    let ws: WebSocket;

    try {
      ws = new WebSocket(url);
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
          setUnreadCount((c) => c + 1);
          // Call external handler (for toast)
          onNotification?.(notif);
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
          msg.type.startsWith("candidate-chat:message: ") &&
          msg.data
        ) {
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
          msg.type.startsWith("presence: ")
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
      clearWsSender();

      // Start polling as fallback
      startPolling();

      // Exponential backoff reconnect: 1s, 2s, 4s, 8s, 16s, max 30s
      const delay = Math.min(
        1000 * Math.pow(2, reconnectAttemptsRef.current),
        30_000,
      );
      reconnectAttemptsRef.current += 1;

      reconnectTimeoutRef.current = setTimeout(() => {
        if (mountedRef.current) {
          connect();
        }
      }, delay);
    };
  }, [token, queryClient, onNotification, startPolling, stopPolling]);

  // Reset unread badge when user opens notification dropdown
  const clearUnread = useCallback(() => {
    setUnreadCount(0);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
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
