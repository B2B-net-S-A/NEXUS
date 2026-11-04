"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

/** Czas podświetlenia wiadomości, do której prowadził link z powiadomienia. */
export const CHAT_MESSAGE_HIGHLIGHT_MS = 2_000;

/**
 * Ile starszych stron czatu doczytujemy w poszukiwaniu wskazanej wiadomości
 * (strona = 50 wiadomości). Głębiej link otwiera czat bez przewinięcia.
 */
export const CHAT_FOCUS_MAX_OLDER_PAGES = 10;

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
 * żeby F5 nie przewijało ponownie.
 *
 * Wiadomość spoza wczytanych stron: z `hasMore` i `loadMore` hook doczytuje
 * starsze strony (najwyżej `CHAT_FOCUS_MAX_OLDER_PAGES`) — okienko „Czaty”
 * prowadzi do PIERWSZEJ nieprzeczytanej, a ta w ruchliwym czacie bywa dalej
 * niż ostatnie 50 wiadomości. Bez tych propsów parametr znika bez przewinięcia.
 *
 * `onFocus` wyłącza „przyklejenie do dołu" czatu; inaczej kolejna wiadomość
 * z gniazda odrzuciłaby widok od wskazanego miejsca.
 */
export function useChatMessageFocus({
  messageIds,
  ready,
  onFocus,
  hasMore = false,
  isLoadingMore = false,
  loadMore,
}: {
  messageIds: readonly number[];
  ready: boolean;
  onFocus?: () => void;
  hasMore?: boolean;
  isLoadingMore?: boolean;
  loadMore?: () => void;
}): number | null {
  const searchParams = useSearchParams();
  const requested = positiveInt(searchParams?.get("msg"));
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const handledRef = useRef<number | null>(null);
  const olderPagesRef = useRef<{ target: number | null; loaded: number }>({
    target: null,
    loaded: 0,
  });
  const onFocusRef = useRef(onFocus);
  onFocusRef.current = onFocus;
  const loadMoreRef = useRef(loadMore);
  loadMoreRef.current = loadMore;
  const found = requested !== null && messageIds.includes(requested);
  const loadedCount = messageIds.length;

  useEffect(() => {
    if (requested === null || !ready || handledRef.current === requested) return;
    if (!found && hasMore && loadMoreRef.current) {
      if (isLoadingMore) return;
      if (olderPagesRef.current.target !== requested) {
        olderPagesRef.current = { target: requested, loaded: 0 };
      }
      if (olderPagesRef.current.loaded < CHAT_FOCUS_MAX_OLDER_PAGES) {
        olderPagesRef.current.loaded += 1;
        loadMoreRef.current();
        return;
      }
    }
    handledRef.current = requested;
    stripMsgParam();
    if (!found) return;
    onFocusRef.current?.();
    document
      .getElementById(chatMessageDomId(requested))
      ?.scrollIntoView({ block: "center" });
    setHighlighted(requested);
  }, [requested, ready, found, hasMore, isLoadingMore, loadedCount]);

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
