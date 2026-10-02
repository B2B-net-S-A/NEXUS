"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { PanelLeftClose, PanelLeftOpen, X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { Tab } from "@/store/tabs";

/**
 * Szyna „Otwarte karty” — pionowa lista ostatnio otwartych rekrutacji albo
 * kandydatów po lewej stronie ekranu (wzorzec z Traffita). Jeden komponent
 * dla obu szyn (02.10.2026): `JobTabsRail` i `CandidateTabsRail` podają mu
 * karty ze wspólnego store'u, nazwy i regułę stanu domyślnego.
 *
 * Trzy postaci:
 * - od 1536 px szyna stoi w układzie strony: rozwinięta (240 px) albo zwinięta
 *   do paska 40 px z licznikiem — wybór jest zapamiętywany;
 * - poniżej 1536 px (laptop z Windows przy skalowaniu 125–150%) lista kart
 *   wysuwa się NAD treść jako nakładka: rozwinięta szyna obok przypiętego menu
 *   zostawiała stronie ~730 px (produkcja 29.09.2026). Wyzwalaczem jest pasek
 *   40 px (`narrow="strip"`, strona rekrutacji) albo zakładka w lewym
 *   marginesie strony (`narrow="gutter"`, listy) — ta druga nie zabiera treści
 *   ani piksela szerokości;
 * - bez otwartych kart nie renderuje nic.
 */

/** Od tej szerokości okna rozwinięta szyna mieści się obok treści. */
const IN_FLOW_MIN_WIDTH = 1536;

/**
 * Pozycjonowanie szyny w układzie strony (`OpenTabsRailFrame`): przyklejona do
 * góry przewijanej treści, od 1024 px. Na telefonie i tablecie w pionie szyny
 * nie ma — tam każdy piksel szerokości należy do treści.
 */
export const OPEN_TABS_RAIL_CLASS =
  "sticky top-0 hidden max-h-[calc(100dvh-7rem)] self-start lg:flex";

/**
 * Czy okno ma co najmniej `minWidth` px. `fallback` obowiązuje do pierwszego
 * pomiaru i tam, gdzie nie ma `matchMedia` (testy) — szyna i tak czeka
 * z renderem na zamontowanie, więc użytkownik go nie widzi.
 */
export function useMinViewportWidth(minWidth: number, fallback: boolean): boolean {
  const [matches, setMatches] = useState(fallback);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(`(min-width: ${minWidth}px)`);
    const update = () => setMatches(mq.matches);
    update();
    mq.addEventListener?.("change", update);
    return () => mq.removeEventListener?.("change", update);
  }, [minWidth]);
  return matches;
}

/**
 * Zapamiętany stan zwinięcia szyny (`"1"` / `"0"` w `localStorage`). Dopóki
 * nikt nie kliknął „Pokaż” ani „Ukryj”, obowiązuje `defaultCollapsed` — może
 * zależeć od strony i szerokości okna, więc idzie za nimi na bieżąco.
 * Zapisany wybór zawsze wygrywa.
 *
 * Odczyt jest w efekcie, nie w inicjalizatorze stanu: serwer renderuje bez
 * `localStorage`, a rozjazd pierwszego renderu to błąd hydratacji.
 */
export function useRailCollapsed(
  storageKey: string,
  defaultCollapsed: boolean,
): [collapsed: boolean, toggle: () => void] {
  const [stored, setStored] = useState<boolean | null>(null);
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      setStored(raw === null ? null : raw === "1");
    } catch {
      /* storage wyłączony — zostaje stan domyślny */
    }
  }, [storageKey]);

  const collapsed = stored ?? defaultCollapsed;
  const toggle = useCallback(() => {
    const next = !collapsed;
    setStored(next);
    try {
      window.localStorage.setItem(storageKey, next ? "1" : "0");
    } catch {
      /* preferencja UI — nie przerywamy interakcji */
    }
  }, [collapsed, storageKey]);
  return [collapsed, toggle];
}

export interface OpenTabsRailLabels {
  /** Nagłówek rozwiniętej szyny, np. „Rekrutacje”. */
  title: string;
  /** Opis licznika, np. „Otwarte karty” (liczbę dopisuje szyna). */
  count: string;
  /** Nazwa rozwiniętej szyny dla czytników ekranu. */
  region: string;
  /** Nazwa zwiniętego paska dla czytników ekranu. */
  collapsedRegion: string;
  /** Przycisk na pasku: nazwa dostępna i podpowiedź. */
  show: string;
  showTitle: string;
  /** Przycisk zwijania w nagłówku rozwiniętej szyny. */
  hide: string;
}

export interface OpenTabsRailProps {
  tabs: readonly Tab[];
  /** Id rekordu z adresu — jego karta jest podświetlona. */
  currentId: number | null;
  icon: ComponentType<{ className?: string }>;
  labels: OpenTabsRailLabels;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onOpen: (tab: Tab) => void;
  onClose: (tab: Tab) => void;
  onCloseAll: () => void;
  /** Zmiana tej wartości (adres strony) zamyka nakładkę. */
  routeKey?: string | null;
  /**
   * Wyzwalacz poniżej 1536 px. `strip` = pasek 40 px w układzie strony.
   * `gutter` = zakładka w lewym marginesie strony, zero szerokości w układzie:
   * na liście kandydatów i rekrutacji pasek z odstępem zabierał tabeli 56 px,
   * a ta przy 1280 px i tak przewija się już w poziomie (pomiar 02.10.2026).
   */
  narrow?: "strip" | "gutter";
  className?: string;
}

export function OpenTabsRail({
  tabs,
  currentId,
  icon: Icon,
  labels,
  collapsed,
  onToggleCollapsed,
  onOpen,
  onClose,
  onCloseAll,
  routeKey,
  narrow = "strip",
  className,
}: OpenTabsRailProps) {
  // Bramka montowania: karty żyją w `localStorage`, więc serwer renderuje
  // pustą listę, a klient pełną — bez bramki to błąd hydratacji.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  const inFlow = useMinViewportWidth(IN_FLOW_MIN_WIDTH, true);
  const [overlayOpen, setOverlayOpen] = useState(false);
  const overlayRef = useRef<HTMLDivElement>(null);

  // Nakładka zamyka się po przejściu na inną stronę, Esc i kliknięciu obok.
  useEffect(() => {
    setOverlayOpen(false);
  }, [routeKey]);
  useEffect(() => {
    if (!overlayOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOverlayOpen(false);
    };
    const onPointer = (event: MouseEvent) => {
      if (!overlayRef.current?.contains(event.target as Node)) setOverlayOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPointer);
    };
  }, [overlayOpen]);

  if (!mounted || tabs.length === 0) return null;

  // Zwinięta: wąski pasek z przyciskiem i licznikiem kart.
  const strip = (onToggle: () => void, stripClassName?: string) => (
    <aside
      className={cn(
        "flex w-10 shrink-0 flex-col items-center rounded-xl border border-border bg-card/60 py-2",
        stripClassName,
      )}
      aria-label={labels.collapsedRegion}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-label={labels.show}
        title={labels.showTitle}
        className="relative rounded p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <PanelLeftOpen className="h-5 w-5" />
        <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold leading-none text-primary-foreground">
          {tabs.length}
        </span>
      </button>
    </aside>
  );

  // Zakładka w lewym marginesie strony: `<main>` ma od 768 px 24 px marginesu
  // (`md:p-6` w `AppShellV2`), a szyna jest widoczna od 1024 px — zakładka
  // (20 px) mieści się w nim cała i zostawia 4 px odstępu od treści.
  const gutterTab = (onToggle: () => void) => (
    <aside className="absolute -left-6 top-0 w-5" aria-label={labels.collapsedRegion}>
      <button
        type="button"
        onClick={onToggle}
        aria-label={labels.show}
        aria-expanded={overlayOpen}
        title={labels.showTitle}
        className="hit-area flex w-full flex-col items-center gap-1 rounded-r-md border border-l-0 border-border bg-card py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <PanelLeftOpen className="h-3.5 w-3.5" aria-hidden />
        <span className="text-[10px] font-semibold leading-none tabular-nums text-primary">
          {tabs.length}
        </span>
      </button>
    </aside>
  );

  const panel = (onHide: () => void, panelClassName?: string) => (
    <aside
      className={cn(
        "flex w-60 shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-card/60",
        panelClassName,
      )}
      aria-label={labels.region}
    >
      <div className="border-b border-border px-3 pb-2 pt-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-base font-bold leading-tight">{labels.title}</h2>
          <button
            type="button"
            onClick={onHide}
            aria-label={labels.hide}
            title="Ukryj"
            className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            {labels.count}: {tabs.length}
          </span>
          <button
            type="button"
            onClick={onCloseAll}
            aria-label="Zamknij wszystkie karty"
            title="Zamknij wszystkie"
            className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-1.5">
        {tabs.map((tab) => {
          // Podświetlenie z adresu, nie z `activeTabId` — zostaje poprawne po
          // „Wstecz” i po wejściu z linku, których store nie zainicjował.
          const isActive = currentId === tab.entityId;
          return (
            <div
              key={tab.id}
              role="button"
              tabIndex={0}
              title={tab.title}
              onClick={() => onOpen(tab)}
              onKeyDown={(e) => {
                // Tylko klawisz na samym wierszu: Enter na „Zamknij kartę”
                // w środku też tu dociera i otwierał kartę zamiast ją zamknąć.
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onOpen(tab);
                }
              }}
              className={cn(
                "group mx-1.5 flex cursor-pointer items-center gap-2 rounded-md py-1.5 pl-2 pr-1 transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-foreground/80 hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon
                className={cn(
                  "h-4 w-4 shrink-0",
                  isActive ? "text-primary" : "text-muted-foreground",
                )}
              />
              <span className="flex-1 truncate text-sm">{tab.title}</span>
              <button
                type="button"
                aria-label="Zamknij kartę"
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(tab);
                }}
                // Przy myszy „×” pojawia się po najechaniu na wiersz; na dotyku
                // i przy fokusie z klawiatury jest widoczny od razu.
                className={cn(
                  "shrink-0 rounded p-0.5 transition-colors",
                  isActive
                    ? "text-primary/70 hover:bg-primary/10 hover:text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:text-foreground pointer-fine:text-transparent pointer-fine:group-hover:text-muted-foreground pointer-fine:hover:text-foreground pointer-fine:focus-visible:text-foreground",
                )}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </nav>
    </aside>
  );

  if (!inFlow) {
    const toggleOverlay = () => setOverlayOpen((open) => !open);
    // Lista kart nie spycha ani nie ściska treści — wysuwa się nad nią
    // i niczego nie zapisuje. Pasek zajmuje swoje 40 px; zakładka (`gutter`)
    // wisi w marginesie strony, a jej opakowanie ma zerową szerokość.
    return (
      <div
        ref={overlayRef}
        className={cn(
          "relative shrink-0",
          narrow === "gutter" ? "w-0" : "w-10",
          // Opakowanie jest przyklejone (`sticky`), więc tworzy własną warstwę:
          // bez `z-30` otwarta lista kart chowała się POD pozycjonowanymi
          // elementami treści (przełącznik zakresu, pigułki filtrów).
          overlayOpen && "z-30",
          className,
        )}
      >
        {narrow === "gutter" ? gutterTab(toggleOverlay) : strip(toggleOverlay)}
        {overlayOpen
          ? panel(
              () => setOverlayOpen(false),
              "absolute left-0 top-0 z-30 max-h-[calc(100dvh-7rem)] bg-card shadow-xl",
            )
          : null}
      </div>
    );
  }

  return collapsed ? strip(onToggleCollapsed, className) : panel(onToggleCollapsed, className);
}

/**
 * Układ strony z szyną po lewej: szyna i treść obok siebie. Gdy szyna nie
 * renderuje nic (brak kart, telefon), treść zajmuje całą szerokość.
 */
export function OpenTabsRailFrame({
  rail,
  children,
  className,
}: {
  rail: ReactNode;
  children: ReactNode;
  /** Odstęp między szyną a treścią (np. `gap-4 lg:gap-6`). */
  className?: string;
}) {
  return (
    <div className={cn("flex items-start", className)}>
      {rail}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

/**
 * Odstęp szyna–treść na LISTACH (`/jobs`, `/candidates`): dopiero od 1536 px,
 * gdy szyna stoi w układzie strony. Poniżej wyzwalaczem jest zakładka
 * w marginesie (`narrow="gutter"`) i odstęp tylko zabierałby liście szerokość.
 */
export const LIST_RAIL_GAP_CLASS = "2xl:gap-6";
