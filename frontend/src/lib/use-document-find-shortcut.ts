"use client";

import { useEffect, useRef, type RefObject } from "react";

/**
 * Ctrl+F / Cmd+F w podglądzie dokumentu ustawia kursor w polu „Szukaj w CV”
 * zamiast otwierać wyszukiwarkę przeglądarki, która przeszukiwała stronę POD
 * oknem podglądu (zgłoszenie 09.2026: „com” → „1 z 36” na liście kandydatów).
 *
 * - `scope: "dialog"` — podgląd w oknie modalnym: skrót działa zawsze, dopóki
 *   okno jest otwarte (i tak zasłania resztę strony).
 * - `scope: "container"` — podgląd osadzony w stronie (profil kandydata):
 *   skrót przejmujemy tylko, gdy kursor myszy albo fokus jest w podglądzie.
 *   W pozostałej części strony Ctrl+F działa jak zawsze. Gdy nad stroną jest
 *   otwarte okno, które nie zawiera tego podglądu, skrót należy do okna.
 */
export function isFindShortcut(event: KeyboardEvent): boolean {
  return (
    (event.ctrlKey || event.metaKey) &&
    !event.altKey &&
    !event.shiftKey &&
    event.key.toLowerCase() === "f"
  );
}

export function useDocumentFindShortcut({
  enabled,
  scope,
  containerRef,
  inputRef,
}: {
  enabled: boolean;
  scope: "dialog" | "container";
  containerRef: RefObject<HTMLElement | null>;
  inputRef: RefObject<HTMLInputElement | null>;
}): void {
  const hoveredRef = useRef(false);

  useEffect(() => {
    if (!enabled || scope !== "container") return;
    const container = containerRef.current;
    if (!container) return;
    const enter = () => {
      hoveredRef.current = true;
    };
    const leave = () => {
      hoveredRef.current = false;
    };
    container.addEventListener("pointerenter", enter);
    container.addEventListener("pointerleave", leave);
    return () => {
      hoveredRef.current = false;
      container.removeEventListener("pointerenter", enter);
      container.removeEventListener("pointerleave", leave);
    };
  }, [enabled, scope, containerRef]);

  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (!isFindShortcut(event)) return;
      const input = inputRef.current;
      const container = containerRef.current;
      if (!input || !container) return;

      if (scope === "container") {
        const active = document.activeElement;
        const focusedInside = active != null && container.contains(active);
        if (!focusedInside && !hoveredRef.current) return;
        const openDialogs = Array.from(
          document.querySelectorAll('[role="dialog"][data-state="open"]'),
        );
        if (openDialogs.some((dialog) => !dialog.contains(container))) return;
      }

      event.preventDefault();
      event.stopPropagation();
      input.focus();
      input.select();
    };
    // Capture: pierwszeństwo przed innymi skrótami strony nasłuchującymi na
    // `window` (np. paleta poleceń).
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [enabled, scope, containerRef, inputRef]);
}
