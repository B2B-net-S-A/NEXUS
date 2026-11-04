"use client";

import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { shouldCloseOnEscape } from "@/lib/panel-escape";

/**
 * Tabela po lewej, panel szczegółów po prawej (Kontrakty i Zamówienia, wersja B).
 *
 * - od 1600 px panel jest kolumną siatki obok tabeli (sticky),
 * - 768–1599 px (laptopy z Windows 1280–1536) panel nachodzi na tabelę z prawej
 *   krawędzi i NIE ściska kolumn — tabela zostaje w pełnej szerokości,
 * - poniżej 768 px panel zajmuje cały ekran.
 *
 * Esc zamyka panel (poza otwartym oknem, menu i polem tekstowym), a fokus
 * wraca do elementu, z którego panel otwarto — zwykle wiersza tabeli.
 */
export const LIST_DETAIL_SIDE_BY_SIDE_QUERY = "(min-width: 1600px)";

export interface ListDetailLayoutProps {
  list: ReactNode;
  /** `null` = panel zamknięty. */
  panel: ReactNode | null;
  onClose: () => void;
  panelLabel: string;
  className?: string;
}

export function ListDetailLayout({ list, panel, onClose, panelLabel, className }: ListDetailLayoutProps) {
  const open = panel != null;
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Zapamiętaj, skąd panel otwarto (przejście zamknięty → otwarty).
  const wasOpen = useRef(false);
  if (open && !wasOpen.current && typeof document !== "undefined") {
    returnFocusRef.current = document.activeElement as HTMLElement | null;
  }
  useEffect(() => {
    if (!open && wasOpen.current) {
      const el = returnFocusRef.current;
      if (el && el.isConnected && typeof el.focus === "function") el.focus({ preventScroll: true });
      returnFocusRef.current = null;
    }
    wasOpen.current = open;
  }, [open]);

  // Obok tabeli (≥ 1600 px) panel kończy się na dole okna, żeby stopka
  // z akcjami była zawsze widoczna. Stała `100dvh - 5rem` wystarczała tylko
  // po przewinięciu strony: nad listą kontraktów panel startuje ~200 px od
  // góry, więc „Zakończ współpracę…” wypadało pod dolną krawędzią ekranu.
  const panelRef = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    if (!open || typeof window === "undefined") return;
    const el = panelRef.current;
    if (!el) return;
    const mq = window.matchMedia?.(LIST_DETAIL_SIDE_BY_SIDE_QUERY);
    let frame = 0;
    const fit = () => {
      frame = 0;
      if (!mq?.matches) {
        el.style.removeProperty("max-height");
        return;
      }
      const top = Math.max(el.getBoundingClientRect().top, 0);
      el.style.maxHeight = `${Math.max(window.innerHeight - top - 16, 360)}px`;
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(fit);
    };
    fit();
    // Baner albo filtry nad listą zmieniają górną krawędź panelu bez scrolla.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    if (el.parentElement) observer?.observe(el.parentElement);
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, { capture: true, passive: true });
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, { capture: true });
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (shouldCloseOnEscape(event)) onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div
      data-list-detail
      data-panel-open={open ? "true" : "false"}
      className={cn(
        "grid grid-cols-1 gap-3",
        open && "min-[1600px]:grid-cols-[minmax(0,1fr)_380px]",
        className,
      )}
    >
      <div className="min-w-0">{list}</div>
      {open && (
        <aside
          ref={panelRef}
          aria-label={panelLabel}
          data-list-detail-panel
          // Trzy rozłączne zakresy zamiast nadpisywania: Tailwind v4 nie
          // gwarantuje, że `min-[1600px]:w-auto` wygra z `md:w-[400px]`
          // (zmierzone 29.09: panel miał 400 px w kolumnie 380 px).
          className={cn(
            "flex flex-col bg-background",
            "max-md:fixed max-md:inset-0 max-md:z-40",
            "md:max-[1599px]:fixed md:max-[1599px]:bottom-0 md:max-[1599px]:right-0 md:max-[1599px]:top-12 md:max-[1599px]:z-40",
            "md:max-[1599px]:w-[400px] md:max-[1599px]:border-l md:max-[1599px]:border-border md:max-[1599px]:shadow-2xl",
            "min-[1600px]:sticky min-[1600px]:top-4 min-[1600px]:max-h-[calc(100dvh-5rem)] min-[1600px]:self-start",
            "min-[1600px]:overflow-hidden min-[1600px]:rounded-lg min-[1600px]:border min-[1600px]:border-border",
          )}
        >
          {panel}
        </aside>
      )}
    </div>
  );
}
