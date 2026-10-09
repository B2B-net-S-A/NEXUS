"use client";

/**
 * Strefa podglądu w panelu osoby (D1–D3, 09.10.2026).
 *
 * Do tej pory podgląd (CV / Wymagania / Po ludzku) stał w prawej połowie
 * panelu 1200 px: strona CV miała 533 px (67%), a na laptopie 1280 × 720
 * widać było z niej ok. 250 px wysokości, bo nad podglądem stała głowa doku,
 * zakładki i przyciski. Teraz panel dzieli się na dużą LEWĄ strefę podglądu
 * (cała wysokość) i stałą prawą kolumnę z dokiem.
 *
 * Stan podglądu (zakładka, wyszukiwane słowo) należy do warsztatu, który żyje
 * głęboko w doku — dlatego treść trafia do strefy portalem, a nie propsem
 * z Tablicy. Strefa jest zamontowana zawsze (poza trybem dzielonym ukryta),
 * więc zwinięcie panelu albo zmiana zakładki nie pobiera pliku CV drugi raz.
 *
 * Poniżej 1024 px szerokości okna (i bez dostawcy: testy, zwykłe strony)
 * `PersonPanelSide` renderuje treść w miejscu — warsztat pokazuje ją wtedy
 * pod przyciskiem „Pokaż CV i wymagania”, jak dotąd.
 */

import {
  createContext,
  useContext,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

/** Tailwind `lg` — od tej szerokości okna panel ma strefę podglądu. */
const SIDE_VIEWPORT_QUERY = "(min-width: 64rem)";

function subscribeViewport(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => undefined;
  const mq = window.matchMedia(SIDE_VIEWPORT_QUERY);
  mq.addEventListener?.("change", onChange);
  return () => mq.removeEventListener?.("change", onChange);
}

function viewportSnapshot(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(SIDE_VIEWPORT_QUERY).matches
  );
}

interface SideContextValue {
  node: HTMLElement | null;
  setNode: (node: HTMLElement | null) => void;
  /** Okno ma co najmniej 1024 px — treść idzie do strefy. */
  wide: boolean;
}

const SideContext = createContext<SideContextValue | null>(null);
/** Czy sekcja warsztatu, z której pochodzi treść, jest teraz widoczna. */
const SideSectionActiveContext = createContext(true);

export function PersonPanelSideProvider({ children }: { children: ReactNode }) {
  const [node, setNode] = useState<HTMLElement | null>(null);
  // Odczyt synchroniczny: efekt po malowaniu zamontowałby podgląd najpierw
  // w miejscu, a potem drugi raz w strefie (drugie pobranie pliku CV).
  const wide = useSyncExternalStore(subscribeViewport, viewportSnapshot, () => false);
  const value = useMemo(() => ({ node, setNode, wide }), [node, wide]);
  return <SideContext.Provider value={value}>{children}</SideContext.Provider>;
}

/** Sekcje warsztatu zostają zamontowane — niewidoczna chowa swój podgląd. */
export function PersonPanelSideSection({ active, children }: { active: boolean; children: ReactNode }) {
  return <SideSectionActiveContext.Provider value={active}>{children}</SideSectionActiveContext.Provider>;
}

export interface PersonPanelSideZoneProps {
  /** Poza trybem dzielonym strefa jest ukryta, ale zamontowana. */
  hidden?: boolean;
  className?: string;
}

/** Lewa strefa panelu — cel portalu. Renderuje ją powłoka panelu (i harness). */
export function PersonPanelSideZone({ hidden = false, className }: PersonPanelSideZoneProps) {
  const ctx = useContext(SideContext);
  return (
    <div
      data-person-side=""
      data-testid="person-panel-side"
      hidden={hidden}
      className={cn("relative hidden min-w-0 flex-1 border-r border-border bg-muted/30 lg:block", className)}
    >
      <p className="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-muted-foreground">
        Podgląd CV i wymagań pojawi się tutaj po wczytaniu karty osoby.
      </p>
      <div ref={ctx?.setNode} className="absolute inset-0" />
    </div>
  );
}

/** Czy treść `PersonPanelSide` trafi do strefy (a nie zostanie w miejscu). */
export function usePersonPanelSideActive(): boolean {
  const ctx = useContext(SideContext);
  return Boolean(ctx?.wide);
}

export interface PersonPanelSideProps {
  children: ReactNode;
  /** Jak pokazać treść, gdy strefy nie ma (wąskie okno, brak dostawcy). */
  inline?: (content: ReactNode) => ReactNode;
}

export function PersonPanelSide({ children, inline }: PersonPanelSideProps) {
  const ctx = useContext(SideContext);
  const active = useContext(SideSectionActiveContext);
  if (!ctx?.wide) return <>{inline ? inline(children) : children}</>;
  // Strefa jeszcze niezmierzona — nic nie montujemy, żeby podgląd nie powstał
  // dwa razy (raz w miejscu, raz w strefie).
  if (!ctx.node) return null;
  return createPortal(
    <div
      hidden={!active}
      data-person-side-content=""
      className="absolute inset-0 flex min-h-0 flex-col bg-background"
    >
      {children}
    </div>,
    ctx.node,
  );
}
