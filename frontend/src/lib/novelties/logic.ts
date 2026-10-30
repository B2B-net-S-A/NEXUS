/**
 * Nowości do przeklikania — czysta logika (decyzja Artura 28.10.2026,
 * `docs/claude/ui/nowosci-do-przeklikania.md`).
 *
 * Treść przychodzi z `GET /api/novelties/mine` (rejestr
 * `backend/app/data/novelties/novelties.json`). Kroki przeklikania wskazują
 * kotwice `data-tour="<id>"` na prawdziwych elementach; krok przechodzi po
 * kliknięciu kotwicy, a krok `ack` przyciskiem „Rozumiem”. Kotwicą może być
 * też `data-help="<id>"` przewodnika ekranu — Start w NEXUSIE chodzi po nich.
 *
 * Start w NEXUSIE (`start: true`, rejestr `start.json`, decyzja Artura
 * 30.10.2026): przeklikania najważniejszych funkcji roli. Bez kropek, kart
 * i licznika ✦ — prowadzi do nich ekran `/start`, a dopóki nie są zaliczone,
 * `StartGate` wpuszcza osobę tylko na pulpit i ekrany przeklikania.
 */

export type NoveltyTier = "dot" | "tour" | "process";

export interface NoveltyStep {
  anchor: string;
  text: string;
  hint: string;
  ack: boolean;
}

export interface Novelty {
  id: string;
  title: string;
  why: string;
  tier: NoveltyTier;
  shipped_on: string;
  where: string;
  href: string;
  dot_anchor: string;
  used_anchor: string | null;
  path_prefix: string | null;
  steps: NoveltyStep[];
  done: boolean;
  /** Przeklikanie „Start w NEXUSIE”, nie nowość. */
  start: boolean;
  completed_via: "tour" | "used" | "dot" | null;
  show_card: boolean;
  required_now: boolean;
  can_postpone: boolean;
}

export type NoveltyEvent =
  "seen" | "card_dismissed" | "postponed" | "toured" | "used" | "dot_clicked";

export interface TourState {
  noveltyId: string;
  step: number;
}

/** Ile nowości czeka na przeklikanie — licznik ✦ w pasku (drobiazgi się nie liczą). */
export function pendingCount(list: readonly Novelty[]): number {
  return list.filter((n) => !n.done && !n.start && n.tier !== "dot").length;
}

/** Nowości, którym należy się kropka (wszystkie niezaliczone). */
export function dotNovelties(list: readonly Novelty[]): Novelty[] {
  return list.filter((n) => !n.done && !n.start);
}

/**
 * Karta nieproszona: pierwsza nowość „do przeklikania” z kropką widoczną
 * na tym ekranie. Zmiana procesu ma własne okno, drobiazg karty nie ma.
 */
export function cardCandidate(
  list: readonly Novelty[],
  visibleAnchors: ReadonlySet<string>,
): Novelty | null {
  return (
    list.find(
      (n) =>
        n.tier === "tour" && n.show_card && visibleAnchors.has(n.dot_anchor),
    ) ?? null
  );
}

/** Okno zmiany procesu dla otwartego ekranu. */
export function requiredForPath(
  list: readonly Novelty[],
  pathname: string,
): Novelty | null {
  return (
    list.find(
      (n) =>
        n.tier === "process" &&
        n.required_now &&
        n.path_prefix != null &&
        pathname.startsWith(n.path_prefix),
    ) ?? null
  );
}

/** Selektor kotwicy: `data-tour` nowości albo `data-help` przewodnika ekranu. */
export function anchorSelector(anchor: string): string {
  return `[data-tour="${anchor}"], [data-help="${anchor}"]`;
}

/** Element kliknięcia leży w kotwicy (albo nią jest). */
export function withinAnchor(
  target: EventTarget | null,
  anchor: string,
): boolean {
  if (!(target instanceof Element)) return false;
  return target.closest(anchorSelector(anchor)) !== null;
}

/**
 * Co zapisać po kliknięciu poza przeklikaniem: drobiazg zalicza klik w jego
 * element, nowość „do przeklikania” i zmianę procesu — użycie w pracy.
 */
export function eventForClick(
  novelty: Novelty,
  target: EventTarget | null,
): NoveltyEvent | null {
  if (novelty.done) return null;
  if (novelty.tier === "dot")
    return withinAnchor(target, novelty.dot_anchor) ? "dot_clicked" : null;
  if (novelty.used_anchor && withinAnchor(target, novelty.used_anchor))
    return "used";
  return null;
}

/** Następny krok po kliknięciu; `null` = kliknięcie nie dotyczy kroku. */
export function advanceTour(
  novelty: Novelty,
  state: TourState,
  target: EventTarget | null,
): TourState | "finished" | null {
  const step = novelty.steps[state.step];
  if (!step || step.ack || !withinAnchor(target, step.anchor)) return null;
  return state.step + 1 >= novelty.steps.length
    ? "finished"
    : { ...state, step: state.step + 1 };
}

/** „Rozumiem” na kroku `ack`. */
export function acknowledgeStep(
  novelty: Novelty,
  state: TourState,
): TourState | "finished" {
  return state.step + 1 >= novelty.steps.length
    ? "finished"
    : { ...state, step: state.step + 1 };
}

const TOUR_KEY = "nexus:novelty-tour:v1";

/** Przeklikanie przeżywa przejście na inny ekran (profil kandydata), nie zamknięcie karty. */
export function readTour(): TourState | null {
  try {
    const raw = window.sessionStorage.getItem(TOUR_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<TourState>;
    return typeof parsed.noveltyId === "string" &&
      typeof parsed.step === "number"
      ? { noveltyId: parsed.noveltyId, step: parsed.step }
      : null;
  } catch {
    return null;
  }
}

export function writeTour(state: TourState | null): void {
  try {
    if (state === null) window.sessionStorage.removeItem(TOUR_KEY);
    else window.sessionStorage.setItem(TOUR_KEY, JSON.stringify(state));
  } catch {
    /* storage zablokowany — przeklikanie działa do przeładowania strony */
  }
}

const SEEN_KEY = "nexus:novelty-seen:v1";

/** `seen` wysyłamy raz na kartę przeglądarki i nowość, nie przy każdym renderze. */
export function markSeenOnce(noveltyId: string): boolean {
  try {
    const seen = new Set<string>(
      JSON.parse(window.sessionStorage.getItem(SEEN_KEY) || "[]"),
    );
    if (seen.has(noveltyId)) return false;
    seen.add(noveltyId);
    window.sessionStorage.setItem(SEEN_KEY, JSON.stringify([...seen]));
    return true;
  } catch {
    return false;
  }
}

export interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

/**
 * Miejsce karty kroku obok podświetlenia: pod, nad, z lewej, z prawej —
 * pierwsze, które mieści się w oknie i nie zasłania celu. Przycisk w stopce
 * panelu (np. „Zakończ współpracę…”) nie ma miejsca pod ani nad sobą.
 */
export function placeBeside(
  target: Rect,
  card: { width: number; height: number },
  viewport: { width: number; height: number },
  gap = 12,
): { top: number; left: number } {
  const clampLeft = (x: number) =>
    Math.min(Math.max(12, x), viewport.width - card.width - 12);
  const clampTop = (y: number) =>
    Math.min(Math.max(12, y), viewport.height - card.height - 12);
  const candidates = [
    { top: target.top + target.height + gap, left: clampLeft(target.left) },
    { top: target.top - card.height - gap, left: clampLeft(target.left) },
    { top: clampTop(target.top), left: target.left - card.width - gap },
    { top: clampTop(target.top), left: target.left + target.width + gap },
  ];
  const fits = (c: { top: number; left: number }) =>
    c.top >= 0 &&
    c.left >= 0 &&
    c.top + card.height <= viewport.height &&
    c.left + card.width <= viewport.width;
  const overlaps = (c: { top: number; left: number }) =>
    c.left < target.left + target.width &&
    c.left + card.width > target.left &&
    c.top < target.top + target.height &&
    c.top + card.height > target.top;
  return candidates.find((c) => fits(c) && !overlaps(c)) ?? candidates[0];
}

// ── Start w NEXUSIE ──────────────────────────────────────────────────────────

export interface StartItem {
  id: string;
  title: string;
  why: string;
  where: string;
  href: string;
  done: boolean;
}

export interface StartStatus {
  /** Front zatrzymuje osobę (blokada włączona, coś jeszcze do przeklikania). */
  enforced: boolean;
  /** Wyłącznik firmowy — widzi go panel „kto już umie”. */
  gate_on: boolean;
  done: number;
  total: number;
  items: StartItem[];
}

/** Ekran Startu. */
export const START_PATH = "/start";

/**
 * Tu zatrzymana osoba wchodzi zawsze: Start, pulpit, logowanie i wybór
 * rekrutacji po pierwszym logowaniu, a także panel „kto już umie” z
 * wyłącznikiem blokady (admin i HoR sami też przechodzą Start).
 */
const START_FREE_PREFIXES = [
  START_PATH,
  "/dashboard",
  "/login",
  "/onboarding",
  "/settings/nowosci",
];

/** Czy ekran jest dostępny przed zaliczeniem Startu. */
export function startAllows(pathname: string, touringStart: boolean): boolean {
  // W trakcie przeklikania Startu prowadzi samo przeklikanie (lista → tablica → panel).
  if (touringStart) return true;
  if (pathname === "/" || pathname === "") return true;
  return START_FREE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
