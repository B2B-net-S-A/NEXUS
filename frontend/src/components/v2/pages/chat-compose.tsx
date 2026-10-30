"use client";

import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type RefCallback,
  type RefObject,
} from "react";
import { Maximize2, Minimize2 } from "lucide-react";

/**
 * Pole wiadomości czatu zespołu i czatu kandydata (zgłoszenie Klaudii
 * 29.10.2026, wariant B z makiet): pole rośnie z tekstem do
 * `CHAT_COMPOSE_MAX_ROWS` linii, a przycisk obok „Wyślij” rozwija je na całe
 * okno czatu. W rozwiniętym polu Enter dodaje linię, Ctrl/⌘+Enter wysyła,
 * Esc zwija — długą wiadomość pisze się jak notatkę.
 */

export const CHAT_COMPOSE_MAX_ROWS = 8;

export const EXPANDED_COMPOSE_HINT = "Enter = nowa linia · Ctrl+Enter wysyła · Esc zwija";

export type ComposeKeyAction = "send" | "collapse" | "cancel" | null;

interface ComposeKey {
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
}

/** Co zrobić z klawiszem w polu wiadomości; `null` = domyślne zachowanie pola. */
export function composeKeyAction(e: ComposeKey, expanded: boolean): ComposeKeyAction {
  if (expanded) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) return "send";
    if (e.key === "Escape") return "collapse";
    return null;
  }
  if (e.key === "Enter" && !e.shiftKey) return "send";
  if (e.key === "Escape") return "cancel";
  return null;
}

interface ChatCompose {
  /** Ref listy wiadomości — zamiast `ref={listRef}`. */
  listCallbackRef: RefCallback<HTMLDivElement>;
  composeExpanded: boolean;
  setComposeExpanded: (expanded: boolean) => void;
}

/**
 * Lista wiadomości obok rosnącego i rozwijanego pola:
 *
 * - pole rośnie → lista maleje; lista, która była przy dole, zostaje przy
 *   dole (bez tego ostatnia wiadomość chowała się pod polem i dlatego do
 *   29.10.2026 pole w czacie nie rosło). Obserwator wisi na ref-callbacku,
 *   bo lista znika przy widoku błędu i wraca po „Spróbuj ponownie”;
 * - rozwinięte pole ukrywa listę (`hidden` zeruje przewinięcie), więc po
 *   zwinięciu lista wraca na dół albo tam, gdzie czytała osoba.
 */
export function useChatCompose(
  listRef: RefObject<HTMLDivElement | null>,
  stickToBottomRef: RefObject<boolean>,
): ChatCompose {
  const [composeExpanded, setExpanded] = useState(false);
  const savedScrollTop = useRef(0);

  const listCallbackRef = useCallback(
    (el: HTMLDivElement | null) => {
      listRef.current = el;
      if (!el || typeof ResizeObserver === "undefined") return;
      const observer = new ResizeObserver(() => {
        if (stickToBottomRef.current) el.scrollTop = el.scrollHeight;
      });
      observer.observe(el);
      return () => observer.disconnect();
    },
    [listRef, stickToBottomRef],
  );

  const setComposeExpanded = useCallback(
    (expanded: boolean) => {
      if (expanded && listRef.current && !listRef.current.hidden) {
        savedScrollTop.current = listRef.current.scrollTop;
      }
      setExpanded(expanded);
    },
    [listRef],
  );

  // Tylko przy zwinięciu — pierwszy render zostawia przewijanie listy w spokoju.
  const wasExpanded = useRef(false);
  useLayoutEffect(() => {
    const collapsed = wasExpanded.current && !composeExpanded;
    wasExpanded.current = composeExpanded;
    const el = listRef.current;
    if (!collapsed || !el) return;
    el.scrollTop = stickToBottomRef.current ? el.scrollHeight : savedScrollTop.current;
  }, [composeExpanded, listRef, stickToBottomRef]);

  return { listCallbackRef, composeExpanded, setComposeExpanded };
}

interface ExpandComposeButtonProps {
  expanded: boolean;
  onToggle: () => void;
}

export function ExpandComposeButton({ expanded, onToggle }: ExpandComposeButtonProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex items-center justify-center w-10 h-10 rounded-lg border border-border text-muted-foreground hover:text-foreground hover:bg-muted"
      aria-label={expanded ? "Zwiń pole" : "Rozwiń pole"}
      aria-pressed={expanded}
      data-tour="chat.compose.expand"
      title={expanded ? "Zwiń pole (Esc)" : "Rozwiń pole na całe okno czatu"}
    >
      {expanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
    </button>
  );
}
