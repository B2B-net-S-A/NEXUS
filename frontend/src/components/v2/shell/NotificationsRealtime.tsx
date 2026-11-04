"use client";

import { useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/Toast";
import { useHasInterviewsWindow } from "@/hooks/useHasInterviewsWindow";
import { useNotifications, type WsNotification } from "@/hooks/useNotifications";
import { CV_TOPIC_QUERY_KEY } from "@/lib/api/boardTasks";
import { formatNotificationText } from "@/lib/notification-format";
import { NOTIFICATION_FRAME_EVENT } from "@/lib/notification-topics";
import { useRealtimeStatus } from "@/store/realtime";

const TOPIC_TOAST_MS = 8_000;

/** Czy ramka daje dymek: decyzja serwera; ramka bez tematu (backend sprzed
 *  16.10.2026) — jak dawniej dzwonek, zawsze. Bez dymka, gdy okienko tego
 *  tematu jest otwarte. */
export function shouldToastFrame(
  notif: Pick<WsNotification, "topic" | "toast">,
  openTopic: string | null,
): boolean {
  if (notif.topic && notif.topic === openTopic) return false;
  return notif.toast ?? true;
}

/**
 * Jedyne gniazdo powiadomień, zamontowane raz w powłoce aplikacji (16.10.2026).
 *
 * Do tej daty gniazdo żyło w dzwonku — bez dzwonka padłyby obecność, czaty na
 * żywo, odświeżenia Tablicy, dymki KPI i sygnały Jarvisa. Ramkę powiadomienia
 * (poza rozmowami i notatkami, które idą do swoich okienek) rozgłaszamy
 * zdarzeniem okna i pokazujemy dymkiem według tematu: dzwonka nie ma, więc to
 * jedyne miejsce, gdzie typ bez ikony („inne”) daje o sobie znać.
 */
export function NotificationsRealtime() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { showActionToast, showInfo } = useToast();
  const hasInterviewsWindow = useHasInterviewsWindow();
  const setConnected = useRealtimeStatus((s) => s.setConnected);

  // Dymek przez refy: stabilny callback nie może zależeć od routera i dymków,
  // bo zmiana jego tożsamości przebudowałaby `connect` i zerwała gniazdo.
  const toastRef = useRef({ router, showActionToast, showInfo });
  toastRef.current = { router, showActionToast, showInfo };

  const onNotification = useCallback(
    (notif: WsNotification) => {
      window.dispatchEvent(
        new CustomEvent<WsNotification>(NOTIFICATION_FRAME_EVENT, { detail: notif }),
      );
      if (notif.topic === "cv") {
        // Ikona „CV” liczy stan; zdarzenie mówi tylko, że coś się zmieniło.
        queryClient.invalidateQueries({ queryKey: CV_TOPIC_QUERY_KEY });
      }
      if (!shouldToastFrame(notif, useRealtimeStatus.getState().openTopic)) return;
      const { router: nav, showActionToast: action, showInfo: info } = toastRef.current;
      const text = formatNotificationText(notif.title);
      if (notif.link) {
        const link = notif.link;
        action(text, {
          actionLabel: "Otwórz",
          durationMs: TOPIC_TOAST_MS,
          onAction: () => nav.push(link),
        });
      } else {
        info(text);
      }
    },
    [queryClient],
  );
  const { wsConnected } = useNotifications({
    onNotification,
    interviewsInWindow: hasInterviewsWindow,
  });
  useEffect(() => {
    setConnected(wsConnected);
  }, [wsConnected, setConnected]);
  return null;
}
