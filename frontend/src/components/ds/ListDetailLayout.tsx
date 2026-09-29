"use client";

import { useEffect, useRef, type ReactNode } from "react";
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
          aria-label={panelLabel}
          data-list-detail-panel
          className={cn(
            "fixed inset-0 z-40 flex flex-col bg-background",
            "md:inset-y-0 md:left-auto md:top-12 md:w-[400px] md:border-l md:border-border md:shadow-2xl",
            "min-[1600px]:sticky min-[1600px]:top-4 min-[1600px]:z-auto min-[1600px]:w-auto min-[1600px]:max-h-[calc(100dvh-5rem)]",
            "min-[1600px]:self-start min-[1600px]:rounded-lg min-[1600px]:border min-[1600px]:shadow-none",
          )}
        >
          {panel}
        </aside>
      )}
    </div>
  );
}
