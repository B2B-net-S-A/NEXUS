"use client";

/**
 * „Pokaż mi, gdzie” — podświetla element oznaczony `data-help="<id>"`.
 *
 * Identyfikator pochodzi z zamkniętej listy kotwic przewodnika ekranu
 * (`backend/app/data/screen_guides/guides.json`), nigdy z selektora
 * wymyślonego przez model. Nakładka nie przechwytuje kliknięć
 * (`pointer-events-none`), znika po kilku sekundach, Esc albo kliknięciu.
 * Brak elementu (inna zakładka, zwinięty panel) = `onMissing`, nigdy cisza.
 */

import { useEffect, useRef, useState } from "react";

export const JARVIS_HIGHLIGHT_EVENT = "nexus:jarvis-highlight";
const RETRY_MS = 150;
const RETRY_FOR_MS = 1500;
const VISIBLE_MS = 4000;
const PAD = 6;

export interface JarvisHighlightDetail {
  anchor: string;
}

export function showHelpAnchor(anchor: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<JarvisHighlightDetail>(JARVIS_HIGHLIGHT_EVENT, { detail: { anchor } }));
}

export function findHelpAnchor(anchor: string): HTMLElement | null {
  const selector = `[data-help="${typeof CSS !== "undefined" && CSS.escape ? CSS.escape(anchor) : anchor}"]`;
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(selector))) {
    const rect = el.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) return el;
  }
  return null;
}

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface Props {
  onShown?: (anchor: string) => void;
  onMissing?: (anchor: string) => void;
}

export function HelpSpotlight({ onShown, onMissing }: Props) {
  const [box, setBox] = useState<Box | null>(null);
  const target = useRef<HTMLElement | null>(null);
  const timers = useRef<number[]>([]);
  const callbacks = useRef({ onShown, onMissing });
  callbacks.current = { onShown, onMissing };

  useEffect(() => {
    const clearTimers = () => {
      timers.current.forEach((t) => window.clearTimeout(t));
      timers.current = [];
    };
    const hide = () => {
      clearTimers();
      target.current = null;
      setBox(null);
    };
    const measure = () => {
      const el = target.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      setBox({ top: r.top - PAD, left: r.left - PAD, width: r.width + 2 * PAD, height: r.height + 2 * PAD });
    };
    const onHighlight = (event: Event) => {
      const anchor = (event as CustomEvent<JarvisHighlightDetail>).detail?.anchor;
      if (!anchor) return;
      hide();
      const started = Date.now();
      const attempt = () => {
        const el = findHelpAnchor(anchor);
        if (el) {
          target.current = el;
          const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
          el.scrollIntoView?.({ block: "center", behavior: reduce ? "auto" : "smooth" });
          measure();
          // Po płynnym przewinięciu pozycja się zmienia — mierzymy ponownie.
          timers.current.push(window.setTimeout(measure, 400));
          timers.current.push(window.setTimeout(hide, VISIBLE_MS));
          callbacks.current.onShown?.(anchor);
          return;
        }
        if (Date.now() - started >= RETRY_FOR_MS) {
          callbacks.current.onMissing?.(anchor);
          return;
        }
        timers.current.push(window.setTimeout(attempt, RETRY_MS));
      };
      attempt();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") hide();
    };
    window.addEventListener(JARVIS_HIGHLIGHT_EVENT, onHighlight);
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", hide);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      clearTimers();
      window.removeEventListener(JARVIS_HIGHLIGHT_EVENT, onHighlight);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", hide);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, []);

  if (!box) return null;
  return (
    <div className="pointer-events-none fixed inset-0 z-[60]" aria-hidden data-testid="help-spotlight">
      <div
        className="absolute rounded-lg ring-2 ring-primary transition-all duration-200"
        style={{
          top: box.top,
          left: box.left,
          width: box.width,
          height: box.height,
          boxShadow: "0 0 0 9999px rgb(0 0 0 / 0.35)",
        }}
      />
    </div>
  );
}
