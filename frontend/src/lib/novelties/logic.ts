/**
 * Nowości do przeklikania — czysta logika (decyzja Artura 28.10.2026,
 * `docs/claude/ui/nowosci-do-przeklikania.md`).
 *
 * Treść przychodzi z `GET /api/novelties/mine` (rejestr
 * `backend/app/data/novelties/novelties.json`). Kroki przeklikania wskazują
 * kotwice `data-tour="<id>"` na prawdziwych elementach; krok przechodzi po
 * kliknięciu kotwicy, a krok `ack` przyciskiem „Rozumiem”.
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
  return list.filter((n) => !n.done && n.tier !== "dot").length;
}

/** Nowości, którym należy się kropka (wszystkie niezaliczone). */
export function dotNovelties(list: readonly Novelty[]): Novelty[] {
  return list.filter((n) => !n.done);
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

/** Element kliknięcia leży w kotwicy `data-tour` (albo nią jest). */
export function withinAnchor(
  target: EventTarget | null,
  anchor: string,
): boolean {
  if (!(target instanceof Element)) return false;
  return target.closest(`[data-tour="${anchor}"]`) !== null;
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
