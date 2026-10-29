"use client";

import { useEffect, type RefObject } from "react";
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

/**
 * Rosnące pole zmniejsza listę wiadomości — lista, która była przy dole,
 * zostaje przy dole. Bez tego ostatnia wiadomość chowała się pod polem i
 * dlatego do 29.10.2026 pole w czacie nie rosło.
 */
export function useListStaysAtBottomOnResize(
  listRef: RefObject<HTMLDivElement | null>,
  stickToBottomRef: RefObject<boolean>,
): void {
  useEffect(() => {
    const el = listRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (stickToBottomRef.current) el.scrollTop = el.scrollHeight;
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [listRef, stickToBottomRef]);
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
      title={expanded ? "Zwiń pole (Esc)" : "Rozwiń pole na całe okno czatu"}
    >
      {expanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
    </button>
  );
}
