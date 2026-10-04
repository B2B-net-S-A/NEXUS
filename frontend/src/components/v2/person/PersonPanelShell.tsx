"use client";

/**
 * Obudowa panelu osoby na Tablicy (jeden panel osoby, 04.10.2026): jedno
 * `aside` po prawej, wąskie (380 px) dla doku i szerokie (760 px) dla trybów,
 * które potrzebują miejsca — przeglądu Delivery Leada przed wysłaniem CV,
 * a od kolejnego kroku także rozwiniętego warsztatu. Zmiana trybu zmienia
 * SZEROKOŚĆ tego samego panelu, więc to, co jest w środku (niewysłana
 * notatka, otwarte sekcje), nie jest odmontowywane.
 *
 * Podkład: w wąskim trybie tylko na tablecie (768–1023 px), gdzie dok nakrywa
 * planszę; w szerokim — na każdej szerokości, jak dawne okno przeglądu.
 * Klik w podkład woła `onBackdropClick` (zamknięcie najwyższej warstwy).
 */

import type { CSSProperties, ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface PersonPanelShellProps {
  wide: boolean;
  /** Panel przykryty innym widokiem (np. starym oknem warsztatu) — ukryty, nie odmontowany. */
  hidden?: boolean;
  /** Górna krawędź pod paskiem strony (px); `null` = domyślne `top-12`. */
  chromeTop: number | null;
  onBackdropClick: () => void;
  children: ReactNode;
}

export function PersonPanelShell({
  wide,
  hidden = false,
  chromeTop,
  onBackdropClick,
  children,
}: PersonPanelShellProps) {
  const top: CSSProperties | undefined = chromeTop != null ? { top: chromeTop } : undefined;
  return (
    <>
      {!hidden ? (
        <div
          aria-hidden="true"
          data-testid="pipeline-dock-backdrop"
          className={cn(
            "fixed inset-x-0 bottom-0 top-12 z-20 bg-card/50 backdrop-blur-[2px]",
            wide ? "block" : "hidden md:block lg:hidden",
          )}
          style={top}
          onClick={onBackdropClick}
        />
      ) : null}
      <aside
        aria-label="Panel osoby"
        data-help="jobs.person.dock"
        data-person-panel=""
        data-wide={wide ? "" : undefined}
        hidden={hidden}
        inert={hidden || undefined}
        className={cn(
          "fixed right-0 top-12 bottom-0 z-30 flex w-full flex-col border-l border-border bg-background shadow-xl",
          wide ? "max-w-[760px]" : "max-w-[380px]",
        )}
        style={top}
      >
        {children}
      </aside>
    </>
  );
}
