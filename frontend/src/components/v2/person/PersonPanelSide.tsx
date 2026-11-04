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
 *
 * Układ podglądu (13.10.2026, zgłoszenie rekrutera): CV i kolumnę z wymaganiami
 * da się zwinąć. Stan siedzi tutaj, a nie w podglądzie, bo od niego zależy też
 * szerokość prawej kolumny panelu (`PersonPanelColumn`) — po zwinięciu CV
 * wymagania i panel dzielą ekran po połowie (D2), po zwinięciu obu panel bierze
 * resztę obok dwóch listew. Układ jest pamiętany per osoba (D4,
 * `lib/person-preview-layout.ts`).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import {
  DEFAULT_PERSON_PREVIEW_LAYOUT,
  personPreviewLayoutKey,
  readPersonPreviewLayout,
  writePersonPreviewLayout,
  type PersonPreviewLayout,
} from "@/lib/person-preview-layout";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

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
  layout: PersonPreviewLayout;
  setLayout: (patch: Partial<PersonPreviewLayout>) => void;
}

const SideContext = createContext<SideContextValue | null>(null);
/** Czy sekcja warsztatu, z której pochodzi treść, jest teraz widoczna. */
const SideSectionActiveContext = createContext(true);

export function PersonPanelSideProvider({ children }: { children: ReactNode }) {
  const [node, setNode] = useState<HTMLElement | null>(null);
  // Odczyt synchroniczny: efekt po malowaniu zamontowałby podgląd najpierw
  // w miejscu, a potem drugi raz w strefie (drugie pobranie pliku CV).
  const wide = useSyncExternalStore(subscribeViewport, viewportSnapshot, () => false);

  // Pamięć czytana w efekcie (jak `kanban-view-preferences.ts`): pierwszy
  // render jest taki sam na serwerze i w przeglądarce. Podgląd ładuje się
  // za `next/dynamic`, więc montuje się już w zapamiętanym układzie.
  const userId = useAuthStore((s) => s.user?.id);
  const layoutKey = personPreviewLayoutKey(userId);
  const [layout, setLayoutState] = useState<PersonPreviewLayout>(DEFAULT_PERSON_PREVIEW_LAYOUT);
  useEffect(() => {
    setLayoutState(readPersonPreviewLayout(layoutKey));
  }, [layoutKey]);
  const setLayout = useCallback(
    (patch: Partial<PersonPreviewLayout>) => {
      const next = { ...layout, ...patch };
      setLayoutState(next);
      writePersonPreviewLayout(layoutKey, next);
    },
    [layout, layoutKey],
  );

  const value = useMemo(() => ({ node, setNode, wide, layout, setLayout }), [node, wide, layout, setLayout]);
  return <SideContext.Provider value={value}>{children}</SideContext.Provider>;
}

export interface PersonPreviewCollapse {
  layout: PersonPreviewLayout;
  setLayout: (patch: Partial<PersonPreviewLayout>) => void;
}

/**
 * Zwijanie CV i wymagań — tylko w powłoce panelu i od 1024 px okna (tam
 * podgląd stoi w strefie). Bez powłoki albo w wąskim oknie `null`: podgląd
 * wygląda jak dotąd.
 */
export function usePersonPreviewCollapse(): PersonPreviewCollapse | null {
  const ctx = useContext(SideContext);
  return useMemo(
    () => (ctx?.wide ? { layout: ctx.layout, setLayout: ctx.setLayout } : null),
    [ctx?.wide, ctx?.layout, ctx?.setLayout],
  );
}

/** Oba elementy podglądu zwinięte — w strefie stoją same listwy. */
function bothCollapsed(layout: PersonPreviewLayout | undefined): boolean {
  return layout?.cvCollapsed === true && layout.infoCollapsed === true;
}

/** Sekcje warsztatu zostają zamontowane — niewidoczna chowa swój podgląd. */
export function PersonPanelSideSection({ active, children }: { active: boolean; children: ReactNode }) {
  return <SideSectionActiveContext.Provider value={active}>{children}</SideSectionActiveContext.Provider>;
}

/**
 * Czy sekcja, z której pochodzi treść, jest teraz widoczna. Układ podglądu jest
 * wspólny dla sekcji, więc podgląd ukrytej sekcji nie montuje po zmianie układu
 * niczego nowego (np. CV, którego nikt nie widzi) — dopiero gdy sekcja wróci.
 */
export function usePersonPanelSideSectionActive(): boolean {
  return useContext(SideSectionActiveContext);
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
      className={cn(
        "relative hidden min-w-0 flex-1 border-r border-border bg-muted/30 lg:block",
        // Dwie listwy podglądu po 2,75rem (`w-11` w `CandidatePreviewPane`).
        bothCollapsed(ctx?.layout) && "lg:w-[5.5rem] lg:flex-none",
        className,
      )}
    >
      <p className="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-muted-foreground">
        Podgląd CV i wymagań pojawi się tutaj po wczytaniu karty osoby.
      </p>
      <div ref={ctx?.setNode} className="absolute inset-0" />
    </div>
  );
}

export interface PersonPanelColumnProps {
  /** Panel w trybie dzielonym — tylko wtedy kolumna ma stałą szerokość obok strefy. */
  split: boolean;
  testId?: string;
  children: ReactNode;
}

/** Najwęższa kolumna panelu i najwęższy podgląd CV obok niej (px). */
const COLUMN_MIN = 400;
const ZONE_MIN = 360;
/** Krok strzałki na uchwycie krawędzi (px). */
const RESIZE_STEP = 40;

export interface PersonPanelConversationMode {
  on: boolean;
  toggle: () => void;
}

const ConversationModeContext = createContext<PersonPanelConversationMode | null>(null);

/**
 * „Tryb rozmowy” (29.10.2026) — tylko w rozwiniętym panelu od 1024 px okna.
 * Bez powłoki, w doku i w wąskim oknie `null`: przełącznika nie ma, a widok
 * jest taki jak dotąd.
 */
export function usePersonPanelConversationMode(): PersonPanelConversationMode | null {
  return useContext(ConversationModeContext);
}

function clampWidth(value: number, max: number): number {
  return Math.round(Math.min(Math.max(value, COLUMN_MIN), Math.max(COLUMN_MIN, max)));
}

/**
 * Prawa kolumna panelu obok strefy podglądu: 460 px, od 1536 px okna 520 px.
 * Po zwinięciu CV połowa szerokości bez listwy (2,75rem), po zwinięciu obu —
 * reszta obok dwóch listew. Szerokości tylko od `lg`: poniżej strefy nie ma.
 *
 * Od 29.10.2026 (zgłoszenie Artura: formularz screeningu za ciasny na
 * laptopie) krawędź kolumny przy widocznym CV da się przeciągnąć (od 400 px
 * do „CV ma jeszcze 360 px”), strzałkami albo myszą; dwuklik i Home wracają
 * do szerokości domyślnej. Szerokość i „Tryb rozmowy” pamięta układ osoby.
 * Kolumna przy zwiniętym CV zostaje regułą D2 (połowa ekranu).
 */
export function PersonPanelColumn({ split, testId = "person-panel-column", children }: PersonPanelColumnProps) {
  const ctx = useContext(SideContext);
  const layout = ctx?.layout ?? DEFAULT_PERSON_PREVIEW_LAYOUT;
  const setLayout = ctx?.setLayout;
  const adjustable = split && ctx?.wide === true;
  const resizable = adjustable && !layout.cvCollapsed;
  const columnRef = useRef<HTMLDivElement>(null);
  // Podczas przeciągania szerokość żyje lokalnie; pamięć zapisuje puszczenie.
  const [dragWidth, setDragWidth] = useState<number | null>(null);
  const columnWidth = resizable ? (dragWidth ?? layout.columnWidth) : null;

  const conversation = useMemo<PersonPanelConversationMode | null>(
    () =>
      adjustable && setLayout
        ? { on: layout.compact, toggle: () => setLayout({ compact: !layout.compact }) }
        : null,
    [adjustable, setLayout, layout.compact],
  );

  let width: string | false = false;
  if (split) {
    if (columnWidth != null) width = "lg:flex-none";
    else if (bothCollapsed(layout)) width = "lg:flex-1";
    else if (layout.cvCollapsed) width = "lg:w-[calc((100%-2.75rem)/2)] lg:flex-none";
    else width = "lg:w-[460px] lg:flex-none 2xl:w-[520px]";
  }

  const maxWidth = (): number => {
    const panel = columnRef.current?.parentElement;
    return (panel?.getBoundingClientRect().width ?? 0) - ZONE_MIN;
  };
  const currentWidth = (): number => columnRef.current?.getBoundingClientRect().width ?? COLUMN_MIN;

  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    const panel = columnRef.current?.parentElement;
    if (!panel || !setLayout || event.button > 0) return;
    event.preventDefault();
    const right = panel.getBoundingClientRect().right;
    const max = maxWidth();
    let last = clampWidth(currentWidth(), max);
    const move = (e: PointerEvent) => {
      last = clampWidth(right - e.clientX, max);
      setDragWidth(last);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setDragWidth(null);
      setLayout({ columnWidth: last });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const onResizeKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!setLayout) return;
    if (event.key === "Home") {
      event.preventDefault();
      setLayout({ columnWidth: null });
      return;
    }
    // Kolumna stoi po prawej: krawędź w lewo = szerzej.
    const delta = event.key === "ArrowLeft" ? RESIZE_STEP : event.key === "ArrowRight" ? -RESIZE_STEP : 0;
    if (delta === 0) return;
    event.preventDefault();
    setLayout({ columnWidth: clampWidth(currentWidth() + delta, maxWidth()) });
  };

  return (
    <div
      ref={columnRef}
      data-testid={testId}
      data-compact={conversation?.on ? "" : undefined}
      className={cn("flex min-h-0 min-w-0 flex-1 flex-col", resizable && "relative", width)}
      // Szerokość z pamięci nie zabiera CV więcej niż do 360 px, także po zmniejszeniu okna.
      style={columnWidth != null ? { width: `min(${columnWidth}px, calc(100% - ${ZONE_MIN}px))` } : undefined}
    >
      {resizable ? (
        <div
          role="separator"
          tabIndex={0}
          aria-orientation="vertical"
          aria-label="Szerokość panelu osoby"
          aria-valuemin={COLUMN_MIN}
          aria-valuenow={columnWidth ?? undefined}
          aria-valuetext={columnWidth != null ? `${columnWidth} px` : "domyślna"}
          title="Przeciągnij, żeby poszerzyć panel · dwuklik: domyślna szerokość"
          data-testid="person-panel-column-resize"
          data-tour="person.panel.column-resize"
          onPointerDown={startResize}
          onDoubleClick={() => setLayout?.({ columnWidth: null })}
          onKeyDown={onResizeKey}
          className="group absolute inset-y-0 -left-1.5 z-10 hidden w-3 cursor-col-resize items-center justify-center focus-visible:outline-none lg:flex"
        >
          <span className="h-full w-px bg-transparent transition-colors group-hover:bg-primary group-focus-visible:bg-primary" />
          <span className="absolute top-1/2 flex h-10 w-2.5 -translate-y-1/2 flex-col items-center justify-center gap-0.5 rounded-full border border-border bg-card shadow-sm group-hover:border-primary group-focus-visible:border-primary group-focus-visible:ring-2 group-focus-visible:ring-ring">
            <span className="h-0.5 w-0.5 rounded-full bg-muted-foreground" />
            <span className="h-0.5 w-0.5 rounded-full bg-muted-foreground" />
            <span className="h-0.5 w-0.5 rounded-full bg-muted-foreground" />
          </span>
        </div>
      ) : null}
      <ConversationModeContext.Provider value={conversation}>{children}</ConversationModeContext.Provider>
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
