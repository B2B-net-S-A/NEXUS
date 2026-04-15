"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useAuthStore } from "@/store/auth";
import { useQueryClient } from "@tanstack/react-query";

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
        } else if (msg.type === "ping") {
          ws.send("ping");
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
