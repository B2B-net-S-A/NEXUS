"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

/** Czas podświetlenia wiadomości, do której prowadził link z powiadomienia. */
export const CHAT_MESSAGE_HIGHLIGHT_MS = 2_000;

export function chatMessageDomId(messageId: number): string {
  return `chat-msg-${messageId}`;
}

function positiveInt(raw: string | null | undefined): number | null {
  if (!raw || !/^\d+$/.test(raw)) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}

function stripMsgParam(): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (!url.searchParams.has("msg")) return;
  url.searchParams.delete("msg");
  window.history.replaceState(
    window.history.state,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}

/**
 * `&msg=<id>` w linku powiadomienia czatu (wzmianka, nowa wiadomość).
 *
 * Do 09.2026 parametr był ignorowany: link otwierał czat przewinięty na dół,
 * a wiadomość, o której mówiło powiadomienie, trzeba było szukać ręcznie.
 * Hook przewija do wiadomości, podświetla ją na 2 s i zdejmuje `msg` z adresu,
 * żeby F5 nie przewijało ponownie. Wiadomość spoza wczytanych stron (starsza
 * niż pierwsza strona) nie jest doczytywana — parametr i tak znika.
 *
 * `onFocus` wyłącza „przyklejenie do dołu" czatu; inaczej kolejna wiadomość
 * z gniazda odrzuciłaby widok od wskazanego miejsca.
 */
export function useChatMessageFocus({
  messageIds,
  ready,
  onFocus,
}: {
  messageIds: readonly number[];
  ready: boolean;
  onFocus?: () => void;
}): number | null {
  const searchParams = useSearchParams();
  const requested = positiveInt(searchParams?.get("msg"));
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const handledRef = useRef<number | null>(null);
  const onFocusRef = useRef(onFocus);
  onFocusRef.current = onFocus;
  const found = requested !== null && messageIds.includes(requested);

  useEffect(() => {
    if (requested === null || !ready || handledRef.current === requested) return;
    handledRef.current = requested;
    stripMsgParam();
    if (!found) return;
    onFocusRef.current?.();
    document
      .getElementById(chatMessageDomId(requested))
      ?.scrollIntoView({ block: "center" });
    setHighlighted(requested);
  }, [requested, ready, found]);

  // Timer w OSOBNYM efekcie, zależnym od `highlighted`. `stripMsgParam` zmienia
  // `useSearchParams` (Next synchronizuje `replaceState`), więc `requested`
  // spada do `null` i cleanup efektu wyżej kasowałby timer — podświetlenie
  // nie gasło nigdy (przegląd 17.09.2026).
  useEffect(() => {
    if (highlighted === null) return;
    const timer = window.setTimeout(
      () => setHighlighted(null),
      CHAT_MESSAGE_HIGHLIGHT_MS,
    );
    return () => window.clearTimeout(timer);
  }, [highlighted]);

  return highlighted;
}
