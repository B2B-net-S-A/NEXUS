"use client";

/**
 * Obudowa panelu osoby na Tablicy (jeden panel osoby, 04.10.2026): jedno
 * `aside` po prawej w czterech rozmiarach:
 * - `dock` (380 px) — dok osoby,
 * - `wide` (760 px) — rozwinięte narzędzia osoby bez podglądu (umowa,
 *   dopasowanie, notatki),
 * - `split` (cała szerokość okna, 09.10.2026) — po LEWEJ duża strefa podglądu
 *   (CV, wymagania, „po ludzku”) na całą wysokość, po prawej stała kolumna
 *   z dokiem: 460 px, od 1536 px szerokości okna 520 px. Poniżej 1024 px
 *   strefy nie ma — warsztat pokazuje podgląd w miejscu,
 * - `review` (cała szerokość okna) — przegląd Delivery Leada, który sam
 *   układa swoje kolumny.
 * Zmiana trybu zmienia SZEROKOŚĆ tego samego panelu, a dzieci stoją zawsze
 * w tym samym miejscu drzewa, więc to, co jest w środku (niewysłana notatka,
 * otwarte sekcje, wpisany formularz), nie jest odmontowywane.
 *
 * `split` i `review` zakrywają też menu boczne (`data-cover` + reguła
 * w `globals.css`): menu ma `z-40`, a panel żyje w kontekście warstw treści
 * strony, więc samym `z-index` panelu nie da się go przykryć.
 *
 * Podkład: w wąskim trybie tylko na tablecie (768–1023 px), gdzie dok nakrywa
 * planszę; w szerokich — na każdej szerokości, jak dawne okno przeglądu.
 * Klik w podkład woła `onBackdropClick` (zamknięcie najwyższej warstwy).
 */

import type { CSSProperties, ReactNode } from "react";

import { PersonPanelSideProvider, PersonPanelSideZone } from "@/components/v2/person/PersonPanelSide";
import { cn } from "@/lib/utils";

export type PersonPanelSize = "dock" | "wide" | "split" | "review";

const SIZE_CLASS: Record<PersonPanelSize, string> = {
  dock: "max-w-[380px]",
  wide: "max-w-[760px]",
  split: "max-w-none",
  review: "max-w-none",
};

/** Rozmiary na całą szerokość okna — zakrywają planszę i menu boczne. */
const COVER_SIZES: ReadonlySet<PersonPanelSize> = new Set(["split", "review"]);

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
  const split = size === "split";
  return (
    <PersonPanelSideProvider>
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
        data-cover={COVER_SIZES.has(size) ? "" : undefined}
        data-size={size}
        hidden={hidden}
        inert={hidden || undefined}
        className={cn(
          "fixed right-0 top-12 bottom-0 z-30 flex w-full border-l border-border bg-background shadow-xl",
          SIZE_CLASS[size],
        )}
        style={top}
      >
        <PersonPanelSideZone hidden={!split} />
        <div
          data-testid="person-panel-column"
          className={cn(
            "flex min-h-0 min-w-0 flex-1 flex-col",
            split && "lg:w-[460px] lg:flex-none 2xl:w-[520px]",
          )}
        >
          {children}
        </div>
      </aside>
    </PersonPanelSideProvider>
  );
}
