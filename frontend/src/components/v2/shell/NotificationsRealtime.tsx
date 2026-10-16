"use client";

import { useCallback, useEffect } from "react";
import { useHasInterviewsWindow } from "@/hooks/useHasInterviewsWindow";
import { useNotifications, type WsNotification } from "@/hooks/useNotifications";
import { NOTIFICATION_FRAME_EVENT } from "@/lib/notification-topics";
import { useRealtimeStatus } from "@/store/realtime";

/**
 * Jedyne gniazdo powiadomień, zamontowane raz w powłoce aplikacji (16.10.2026).
 *
 * Do tej daty gniazdo żyło w dzwonku — bez dzwonka padłyby obecność, czaty na
 * żywo, odświeżenia Tablicy, dymki KPI i sygnały Jarvisa. Ramkę powiadomienia
 * (poza rozmowami i notatkami, które idą do swoich okienek) rozgłaszamy
 * zdarzeniem okna; okienka paska same decydują, co z nią zrobić.
 */
export function NotificationsRealtime() {
  const hasInterviewsWindow = useHasInterviewsWindow();
  const setConnected = useRealtimeStatus((s) => s.setConnected);
  // Stabilny callback: zmiana tożsamości przebudowałaby `connect` i zerwała gniazdo.
  const onNotification = useCallback((notif: WsNotification) => {
    window.dispatchEvent(
      new CustomEvent<WsNotification>(NOTIFICATION_FRAME_EVENT, { detail: notif }),
    );
  }, []);
  const { wsConnected } = useNotifications({
    onNotification,
    interviewsInWindow: hasInterviewsWindow,
  });
  useEffect(() => {
    setConnected(wsConnected);
  }, [wsConnected, setConnected]);
  return null;
}
