"use client";

import { useEffect, type RefObject } from "react";

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
 *
 * Dwa dokumenty w jednym oknie (oryginał obok CV firmowego, 03.11.2026): skrót
 * dostaje ten pod kursorem albo z fokusem, a gdy to nie żaden osadzony, ten
 * z zakresem okna. Stąd dwa miejsca nasłuchu niżej.
 */
// Podgląd pod kursorem, wspólny dla wszystkich podglądów na ekranie.
let hoveredViewer: HTMLElement | null = null;

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
  useEffect(() => {
    if (!enabled) return;
    const container = containerRef.current;
    if (!container) return;
    const enter = () => {
      hoveredViewer = container;
    };
    const leave = () => {
      if (hoveredViewer === container) hoveredViewer = null;
    };
    container.addEventListener("pointerenter", enter);
    container.addEventListener("pointerleave", leave);
    return () => {
      leave();
      container.removeEventListener("pointerenter", enter);
      container.removeEventListener("pointerleave", leave);
    };
  }, [enabled, containerRef]);

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
        const hovered = hoveredViewer === container;
        // Fokus zostaje w polu po szukaniu, więc kursor nad innym podglądem
        // jest ważniejszy: porównuje się ten sam wyraz w obu dokumentach.
        if (!hovered && (!focusedInside || hoveredViewer != null)) return;
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
    // `window` (np. paleta poleceń). Zdarzenie idzie w capture z `window` do
    // `document`, więc osadzony podgląd, który wziął skrót (`stopPropagation`),
    // wyprzedza podgląd z zakresem okna niezależnie od kolejności montowania.
    const target = scope === "dialog" ? document : window;
    target.addEventListener("keydown", onKeyDown as EventListener, true);
    return () => target.removeEventListener("keydown", onKeyDown as EventListener, true);
  }, [enabled, scope, containerRef, inputRef]);
}
