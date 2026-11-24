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
  /** Ekran na rekrutacji ćwiczebnej Poligonu, gdzie stoi element (porcja dnia). */
  practice_href: string | null;
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

/** Poranna porcja nowości (`GET /api/novelties/daily`, 18.11.2026). */
export interface DailyStatus {
  /** Wyłącznik porcji dla całej firmy (admin, HoR). */
  gate_on: boolean;
  /** Zostało coś do przeklikania i porcja obowiązuje tę osobę. */
  enforced: boolean;
  today: string;
  /** Lekcje na dziś: zaliczone i czekające (od 23.11.2026). */
  done: number;
  total: number;
  /** Wpisy lekcji z dziś — kroki pokazu dla warstwy przeklikania. */
  items: Novelty[];
  /** Lekcje na dziś (najwyżej 5, w piątek z powtórką). */
  lessons: import("./lessons").Lesson[];
  /** Ile lekcji przechodzi na kolejne dni. */
  later: number;
  /** Ile wpisów obejmują dzisiejsze lekcje. */
  novelty_count: number;
  postponed_until: string | null;
  can_postpone: boolean;
  postpone_options: { key: string; label: string; until: string }[];
  /** Admin może pominąć porcję dnia (Artur, 23.11.2026). */
  can_skip: boolean;
  skipped: boolean;
}

export interface TourState {
  noveltyId: string;
  step: number;
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
 * Każde kliknięcie na stronie, z elementem, w który osoba naprawdę kliknęła.
 * Wyzwalacze menu Radix (DropdownMenu, Select) otwierają się na `pointerdown`
 * i ustawiają `body { pointer-events: none }`, więc `click` przychodzi wtedy
 * na `<html>` (wspólny przodek). Gdy `click` trafił w przodka elementu
 * z `pointerdown`, liczy się ten element. Bez tego „Zmień plik” w panelu
 * osoby nie zaliczał kropki nikomu (14.11.2026: 23 widzących, 0 zaliczeń).
 */
export function onEveryClick(
  doc: Document,
  handler: (target: EventTarget | null) => void,
): () => void {
  let down: EventTarget | null = null;
  const onDown = (event: Event) => {
    down = event.target;
  };
  const onClick = (event: Event) => {
    const target = event.target;
    const pressed = down;
    down = null;
    handler(
      pressed instanceof Node &&
        target instanceof Node &&
        target !== pressed &&
        target.contains(pressed)
        ? pressed
        : target,
    );
  };
  doc.addEventListener("pointerdown", onDown, true);
  doc.addEventListener("click", onClick, true);
  return () => {
    doc.removeEventListener("pointerdown", onDown, true);
    doc.removeEventListener("click", onClick, true);
  };
}

/**
 * Klik w kartę nad oknem Radix (okno ćwiczenia Poligonu, karta lekcji, karta
 * kroku) nie zamyka tego okna, gdy `when()` w chwili kliknięcia mówi „tak”.
 * Radix zamyka dialog po `pointerdown` poza nim (nasłuch na dokumencie w fazie
 * bąbelkowej, zamknięcie przy `click`). Natywny nasłuch na karcie zatrzymuje
 * zdarzenie, zanim tam dojdzie; nasłuchy w fazie przechwytywania
 * (`onEveryClick`) dostają je dalej. Ref-callback z funkcją sprzątającą.
 */
export function keepDialogsOpenIf(
  when: () => boolean,
): (el: HTMLElement | null) => (() => void) | void {
  return (el) => {
    if (!el) return;
    const stop = (event: PointerEvent) => {
      if (when()) event.stopPropagation();
    };
    el.addEventListener("pointerdown", stop);
    return () => el.removeEventListener("pointerdown", stop);
  };
}

export const keepDialogsOpen = keepDialogsOpenIf(() => true);

/** Okno (dialog Radix), w którym stoi kotwica; `null`, gdy jej nie ma albo stoi poza oknem. */
function dialogOf(anchor: string): Element | null {
  return (
    document
      .querySelector(anchorSelector(anchor))
      ?.closest('[role="dialog"], [role="alertdialog"]') ?? null
  );
}

/**
 * Następny krok przeklikania stoi w tym samym otwartym oknie co bieżący
 * („Co zmienił klient?”: pole treści → „Przygotuj zmiany”).
 */
export function nextStepInSameDialog(
  current: string,
  next: string | null | undefined,
): boolean {
  if (!next) return false;
  const here = dialogOf(current);
  return here !== null && here === dialogOf(next);
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

export interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

/**
 * Rozmiar karty kroku do wyboru miejsca obok celu. Wysokość to najwyższa
 * karta: dwulinijkowy tytuł i krok „Rozumiem” z dopiskiem „Tutaj tego miejsca
 * nie widać…” mają do 240 px. Przy 170 px karta pod celem wychodziła poza
 * okno 1280 × 720 i „Rozumiem” było ucięte (tester 19.11.2026).
 */
export const TOUR_STEP_CARD = { width: 340, height: 250 } as const;

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
  const chosen = candidates.find((c) => fits(c) && !overlaps(c));
  if (chosen) return chosen;
  // Cel prawie na cały ekran: karta wchodzi na cel, ale nigdy poza okno, bo ma
  // „Rozumiem” i „Przerwij”.
  return {
    top: clampTop(candidates[0].top),
    left: clampLeft(candidates[0].left),
  };
}

/** Wspólna część dwóch prostokątów; `null`, gdy się nie stykają. */
export function intersectRects(a: Rect, b: Rect): Rect | null {
  const left = Math.max(a.left, b.left);
  const top = Math.max(a.top, b.top);
  const right = Math.min(a.left + a.width, b.left + b.width);
  const bottom = Math.min(a.top + a.height, b.top + b.height);
  return right > left && bottom > top
    ? { top, left, width: right - left, height: bottom - top }
    : null;
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
  /** Wyłącznik blokady Poligonu nowych osób (osobny od Startu, 15.11.2026). */
  poligon_gate_on?: boolean;
  done: number;
  total: number;
  items: StartItem[];
  /** Dokąd prowadzi blokada: `/poligon`, dopóki nowa osoba nie skończy poligonu. */
  redirect?: string;
  /** Poligon NEXUSA osoby (`null`, gdy jej rola go nie ma). */
  poligon?: PoligonStatus | null;
}

/** Postęp osoby na Poligonie NEXUSA (zaliczone ćwiczenia z id `poligon-…`). */
export interface PoligonStatus {
  open: boolean;
  /** Poligon blokuje pracę, dopóki go nie przejdzie (nowa osoba). */
  required: boolean;
  /** Ćwiczenia, które liczy licznik i blokada: wymagane od osoby (od nadania
   *  roli z poligonem, 15.11.2026), a gdy poligon nie jest wymagany — cała
   *  ścieżka jej ról. Starszy serwer bez pola = cała ścieżka. */
  exercise_ids?: string[];
  done_ids: string[];
  done: number;
  total: number;
  /** Poligon dla obecnych (16.11.2026): termin i ćwiczenia zaliczone z pracy. */
  luki?: PoligonLuki | null;
}

/** Kampania „tylko luki”: do terminu poligon prosi, po terminie blokuje. */
export interface PoligonLuki {
  /** Termin (YYYY-MM-DD, kalendarz firmy). */
  due: string;
  /** Ćwiczenia zaliczone z pracy z ostatnich 60 dni. */
  credited_ids: string[];
}

/** „Kto zna NEXUS” — rekruterzy × ważne funkcje z 60 dni pracy (HoR). */
export interface LukiMatrix {
  window_days: number;
  features: Array<{ key: string; label: string; group: string; users: number }>;
  people: Array<{
    id: number;
    name: string;
    used: string[];
    gaps: number;
    poligon: { done: number; total: number } | null;
  }>;
  campaign: { due: string; started_at: string | null } | null;
}

/** Termin kampanii po polsku: „pt 21.11”. */
export function formatLukiDue(due: string): string {
  const [y, m, d] = due.split("-").map(Number);
  const day = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  const names = ["nd", "pn", "wt", "śr", "cz", "pt", "sb"];
  return `${names[day]} ${String(d).padStart(2, "0")}.${String(m).padStart(2, "0")}`;
}

/** Ile ćwiczeń z luk zostało osobie (bez kampanii albo po wszystkim: 0). */
export function lukiLeft(poligon: PoligonStatus | null | undefined): number {
  if (!poligon?.luki) return 0;
  return Math.max(poligon.total - poligon.done, 0);
}

/** Ekran Startu. */
export const START_PATH = "/start";

/** Mapa ćwiczeń Poligonu NEXUSA. */
export const POLIGON_PATH = "/poligon";

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
  // Poligon NEXUSA: mapa ćwiczeń (same ćwiczenia przepuszcza `useStartGate`).
  POLIGON_PATH,
  // Sam odczyt liczb na telefonie; przeklikania Startu i tak robi się na laptopie.
  "/podglad",
];

/**
 * Dokąd po „Zakończ onboarding”. Nowa osoba z Poligonem wymaganym idzie od razu
 * na `/poligon` (22.11.2026: lądowała na pulpicie, wolnym od blokady, i Poligon
 * widziała dopiero po kliknięciu innego ekranu). Sam Start i brak stanu
 * (awaria = brak blokady) zostawiają pulpit.
 */
export function afterOnboardingPath(status: StartStatus | null): string {
  if (status?.enforced && status.redirect === POLIGON_PATH) return POLIGON_PATH;
  return "/";
}

/** Czy ekran jest dostępny przed zaliczeniem Startu. */
export function startAllows(pathname: string, touringStart: boolean): boolean {
  // W trakcie przeklikania Startu prowadzi samo przeklikanie (lista → tablica → panel).
  if (touringStart) return true;
  if (pathname === "/" || pathname === "") return true;
  return START_FREE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
