/**
 * Odświeżenie ikony „CV” (`/api/board-tasks/cv`) po ramce gniazda (18.11.2026).
 *
 * W szczycie 18.11 trasa miała 1 380 wywołań w 80 min przy odpytywaniu co 5 min:
 * 25 aktywnych kont rekruterów i DL to ok. 0,73 odczytu na osobę na minutę
 * zamiast 0,2. Log pokazywał serie jednego klienta — 16 odczytów z tą samą
 * liczbą zapytań w 8 s — bo każda ramka (`pipeline_changed` z kilku rekrutacji,
 * każda z własnym oknem debounce, i ramki tematu `cv`) unieważniała klucz osobno,
 * a `invalidateQueries` przerywa trwający odczyt i zaczyna nowy. Serwer liczył
 * każdy z nich (22–34 zapytania).
 *
 * Teraz: pierwsza ramka odświeża od razu (pojedyncze zdarzenie jak dawniej),
 * kolejne w oknie `CV_TOPIC_REFRESH_WINDOW_MS` dają jedno odświeżenie na jego
 * końcu — po ostatniej ramce, więc nic nie zostaje nieaktualne. Ukryta karta
 * tylko oznacza dane jako nieaktualne (odpytywanie i tak stoi przy ukrytej
 * karcie); `useCvTopic` pobiera je przy powrocie na kartę.
 *
 * Własne akcje (ruch karty, QC, przegląd) odświeżają ikonę bezpośrednio, bez
 * tego okna.
 */

import type { QueryClient } from "@tanstack/react-query";

import { CV_TOPIC_QUERY_KEY } from "@/lib/api/boardTasks";

export const CV_TOPIC_REFRESH_WINDOW_MS = 2_000;

interface WindowState {
  timer: ReturnType<typeof setTimeout>;
  trailing: boolean;
}

const windows = new WeakMap<QueryClient, WindowState>();

function invalidateNow(queryClient: QueryClient): void {
  const hidden =
    typeof document !== "undefined" && document.visibilityState === "hidden";
  void queryClient.invalidateQueries({
    queryKey: CV_TOPIC_QUERY_KEY,
    refetchType: hidden ? "none" : "active",
  });
}

function openWindow(queryClient: QueryClient): void {
  const state: WindowState = {
    trailing: false,
    timer: setTimeout(() => {
      windows.delete(queryClient);
      if (state.trailing) {
        invalidateNow(queryClient);
        openWindow(queryClient);
      }
    }, CV_TOPIC_REFRESH_WINDOW_MS),
  };
  windows.set(queryClient, state);
}

/** Ikona „CV” po zdarzeniu z gniazda: od razu albo raz na końcu okna. */
export function refreshCvTopicFromRealtime(queryClient: QueryClient): void {
  const open = windows.get(queryClient);
  if (open) {
    open.trailing = true;
    return;
  }
  invalidateNow(queryClient);
  openWindow(queryClient);
}
