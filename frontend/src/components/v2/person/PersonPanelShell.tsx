"use client";

/**
 * Obudowa panelu osoby na Tablicy (jeden panel osoby, 04.10.2026): jedno
 * `aside` po prawej w trzech szerokościach:
 * - `dock` (380 px) — dok osoby,
 * - `wide` (760 px) — przegląd Delivery Leada przed wysłaniem CV i rozwinięte
 *   narzędzia osoby,
 * - `split` (do 1200 px, 0424, 07.10.2026) — formularz screeningu albo profil
 *   przed telefonem po lewej i podgląd CV / wymagań po prawej (D3: „od razu
 *   z boku”).
 * Zmiana trybu zmienia SZEROKOŚĆ tego samego panelu, więc to, co jest
 * w środku (niewysłana notatka, otwarte sekcje, wpisany formularz), nie jest
 * odmontowywane.
 *
 * Podkład: w wąskim trybie tylko na tablecie (768–1023 px), gdzie dok nakrywa
 * planszę; w szerokich — na każdej szerokości, jak dawne okno przeglądu.
 * Klik w podkład woła `onBackdropClick` (zamknięcie najwyższej warstwy).
 */

import type { CSSProperties, ReactNode } from "react";

import { cn } from "@/lib/utils";

export type PersonPanelSize = "dock" | "wide" | "split";

const SIZE_CLASS: Record<PersonPanelSize, string> = {
  dock: "max-w-[380px]",
  wide: "max-w-[760px]",
  split: "max-w-[min(1200px,100vw)]",
};

export interface PersonPanelShellProps {
  size: PersonPanelSize;
  /** Panel przykryty innym widokiem (np. starym oknem warsztatu) — ukryty, nie odmontowany. */
  hidden?: boolean;
  /** Górna krawędź pod paskiem strony (px); `null` = domyślne `top-12`. */
  chromeTop: number | null;
  onBackdropClick: () => void;
  children: ReactNode;
}

export function PersonPanelShell({
  size,
  hidden = false,
  chromeTop,
  onBackdropClick,
  children,
}: PersonPanelShellProps) {
  const top: CSSProperties | undefined = chromeTop != null ? { top: chromeTop } : undefined;
  const wide = size !== "dock";
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
        data-size={size}
        hidden={hidden}
        inert={hidden || undefined}
        className={cn(
          "fixed right-0 top-12 bottom-0 z-30 flex w-full flex-col border-l border-border bg-background shadow-xl",
          SIZE_CLASS[size],
        )}
        style={top}
      >
        {children}
      </aside>
    </>
  );
}
