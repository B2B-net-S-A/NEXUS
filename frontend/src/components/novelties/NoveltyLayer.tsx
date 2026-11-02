"use client";

/**
 * Nowości do przeklikania — warstwa nad prawdziwym ekranem
 * (decyzja Artura 28.10.2026, `docs/claude/ui/nowosci-do-przeklikania.md`).
 *
 * - kropka „Nowe” przy kotwicy `data-tour` każdej niezaliczonej nowości;
 * - karta „Przeklikaj” przy kropce: sama z siebie raz, w budżecie dymków
 *   Jarvisa (3 dziennie, nigdy przy otwartym oknie), albo po kliknięciu kropki;
 * - przeklikanie: podświetlony prawdziwy element, krok przechodzi po jego
 *   kliknięciu (krok `ack` — przyciskiem „Rozumiem”), także po przejściu
 *   na inny ekran;
 * - okno zmiany procesu przy wejściu na `path_prefix`, odłożyć raz.
 *
 * Zalicza przeklikanie albo kliknięcie kotwicy `used_anchor` w pracy.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { CheckCircle2, Clock, Sparkles, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  canShowUnsolicited,
  recordUnsolicited,
} from "@/lib/jarvis/bubble-budget";
import { useMyNovelties, useNoveltyEvent } from "@/lib/novelties/api";
import {
  acknowledgeStep,
  anchorSelector,
  advanceTour,
  cardCandidate,
  dotNovelties,
  eventForClick,
  intersectRects,
  markSeenOnce,
  placeBeside,
  readTour,
  requiredForPath,
  START_PATH,
  writeTour,
  type Novelty,
  type Rect,
  type TourState,
} from "@/lib/novelties/logic";
import { useAuthStore } from "@/store/auth";

export const NOVELTY_TOUR_START_EVENT = "nexus:novelty-tour-start";

/** Start przeklikania z listy „Nowości” w pasku (inny komponent). */
export function startNoveltyTour(noveltyId: string): void {
  writeTour({ noveltyId, step: 0 });
  window.dispatchEvent(new CustomEvent(NOVELTY_TOUR_START_EVENT));
}

/**
 * `visible` — element widać; `covered` — leży pod otwartym panelem;
 * `offscreen` — jest, ale poza widokiem (okno, przewijany kontener).
 */
type BoxState = "visible" | "covered" | "offscreen";

interface Box extends Rect {
  state: BoxState;
  /** Widać prawie cały element, więc nie ma po co przewijać. */
  whole: boolean;
}

const PAD = 6;
/** Rozmiar karty kroku do wyboru miejsca obok celu (wysokość z zapasem na dwie linie). */
const STEP_CARD = { width: 340, height: 170 };
/** Tablica ma ponad 100 kart z tą samą kotwicą, a pomiar idzie co 400 ms. */
const MAX_MEASURED = 30;

function rectOf(el: Element): Rect {
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

function anchorElements(anchor: string): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(anchorSelector(anchor)),
  )
    .filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    })
    .slice(0, MAX_MEASURED);
}

/** Część elementu, którą naprawdę widać: okno i przycinający przodkowie. */
function visiblePart(el: HTMLElement): Rect | null {
  let part = intersectRects(rectOf(el), {
    top: 0,
    left: 0,
    width: window.innerWidth,
    height: window.innerHeight,
  });
  for (
    let node: HTMLElement | null = el;
    part && node && node !== document.documentElement;
    node = node.parentElement
  ) {
    const style = getComputedStyle(node);
    if (style.position === "fixed") break;
    if (
      node !== el &&
      (style.overflowX !== "visible" || style.overflowY !== "visible")
    )
      part = intersectRects(part, rectOf(node));
  }
  return part;
}

/** Na wszystkich próbkach leży coś innego niż element (nie liczymy warstwy nowości). */
function coveredByOtherLayer(el: HTMLElement, part: Rect): boolean {
  if (typeof document.elementsFromPoint !== "function") return false;
  return [0.5, 0.25, 0.75].every((f) => {
    const top = document
      .elementsFromPoint(part.left + part.width * f, part.top + part.height * f)
      .find((hit) => !hit.closest('[data-testid^="novelty-"]'));
    return Boolean(top && !el.contains(top) && !top.contains(el));
  });
}

function padded(rect: Rect, state: BoxState, whole: boolean): Box {
  return {
    top: rect.top - PAD,
    left: rect.left - PAD,
    width: rect.width + 2 * PAD,
    height: rect.height + 2 * PAD,
    state,
    whole,
  };
}

/**
 * Z wielu elementów (karty tablicy, wiersze listy) bierze ten, który widać,
 * a nie pierwszy z brzegu, bo po przewinięciu pierwszy leży nad oknem. Pudełko
 * to widoczna część, więc wycięcie nigdy nie stoi nad pustym miejscem.
 */
function measureAnchor(anchor: string): Box | null {
  const elements = anchorElements(anchor);
  if (elements.length === 0) return null;
  let partial: Box | null = null;
  let covered: Box | null = null;
  for (const el of elements) {
    const part = visiblePart(el);
    if (!part) continue;
    if (coveredByOtherLayer(el, part)) {
      covered ??= padded(part, "covered", false);
      continue;
    }
    const full = rectOf(el);
    const whole = part.width * part.height >= 0.9 * full.width * full.height;
    if (whole) return padded(part, "visible", true);
    // Same ucięte (wąska kolumna tytułów): ten, którego widać najwięcej.
    const box = padded(part, "visible", false);
    if (!partial || box.width * box.height > partial.width * partial.height)
      partial = box;
  }
  return (
    partial ?? covered ?? padded(rectOf(elements[0]), "offscreen", false)
  );
}

/** Przewija do elementu; prędkość zgodna z ustawieniem „mniej ruchu”. */
function revealAnchor(anchor: string): void {
  const el = anchorElements(anchor)[0];
  if (!el) return;
  const reduce = window.matchMedia?.(
    "(prefers-reduced-motion: reduce)",
  ).matches;
  el.scrollIntoView?.({
    block: "center",
    inline: "center",
    behavior: reduce ? "auto" : "smooth",
  });
}

function modalOpen(): boolean {
  return Boolean(
    document.querySelector(
      '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]',
    ),
  );
}

/**
 * Pozycje kotwic: co 400 ms (okna, zmiana ekranu) oraz przy przewijaniu
 * i zmianie rozmiaru, żeby wycięcie nie zostawało w tyle za elementem.
 * `focus` to kotwica bieżącego kroku: raz na krok przewijamy do niej, gdy nie
 * widać jej całej. Potem osoba może przewijać, gdzie chce.
 */
function useAnchorBoxes(
  anchors: readonly string[],
  focus: string | null,
): Map<string, Box> {
  const [boxes, setBoxes] = useState<Map<string, Box>>(new Map());
  const key = anchors.join("|");
  const focusRef = useRef(focus);
  focusRef.current = focus;
  const revealed = useRef<string | null>(null);
  useEffect(() => {
    if (!key) {
      setBoxes(new Map());
      return;
    }
    const list = key.split("|");
    const tick = () => {
      const next = new Map<string, Box>();
      for (const anchor of list) {
        const box = measureAnchor(anchor);
        if (box) next.set(anchor, box);
      }
      setBoxes((prev) => (sameBoxes(prev, next) ? prev : next));
      const current = focusRef.current;
      const box = current ? next.get(current) : null;
      // Dopiero gdy nie widać całości: panel doczytuje treść i element spada
      // poza ekran chwilę po tym, jak się pojawił.
      if (
        current &&
        box &&
        box.state !== "covered" &&
        !box.whole &&
        revealed.current !== current
      ) {
        revealed.current = current;
        revealAnchor(current);
      }
    };
    tick();
    const id = window.setInterval(tick, 400);
    let frame = 0;
    const onMove = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        tick();
      });
    };
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    return () => {
      window.clearInterval(id);
      if (frame) window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
    };
  }, [key]);
  return boxes;
}

function sameBoxes(a: Map<string, Box>, b: Map<string, Box>): boolean {
  if (a.size !== b.size) return false;
  for (const [k, v] of b) {
    const o = a.get(k);
    if (
      !o ||
      o.top !== v.top ||
      o.left !== v.left ||
      o.width !== v.width ||
      o.height !== v.height ||
      o.state !== v.state ||
      o.whole !== v.whole
    )
      return false;
  }
  return true;
}

function Dot({
  box,
  label,
  onClick,
}: {
  box: Box;
  label: string;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Nowe: ${label}`}
      title={`Nowe: ${label}`}
      className={`fixed z-[55] flex h-3.5 w-3.5 ${onClick ? "" : "pointer-events-none"}`}
      style={{ top: box.top, left: box.left + box.width - 10 }}
      data-testid="novelty-dot"
    >
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60 motion-reduce:animate-none" />
      <span className="relative inline-flex h-3.5 w-3.5 rounded-full border-2 border-card bg-primary" />
    </button>
  );
}

function NoveltyCard({
  novelty,
  box,
  onTour,
  onLater,
}: {
  novelty: Novelty;
  box: Box;
  onTour: () => void;
  onLater: () => void;
}) {
  const left = Math.min(Math.max(12, box.left - 24), window.innerWidth - 372);
  const below = box.top + box.height + 230 < window.innerHeight;
  return (
    <div
      role="dialog"
      aria-label={`Nowość: ${novelty.title}`}
      className="fixed z-[56] w-[360px] rounded-xl border border-primary/30 bg-card p-4 shadow-xl"
      style={
        below
          ? { top: box.top + box.height + 10, left }
          : { bottom: window.innerHeight - box.top + 10, left }
      }
      data-testid="novelty-card"
    >
      <div className="flex items-center gap-2">
        <Badge variant="soft" size="sm" uppercase>
          Nowe · {formatShipped(novelty.shipped_on)}
        </Badge>
        <span className="text-xs text-muted-foreground">{novelty.where}</span>
      </div>
      <p className="mt-2 text-sm font-semibold text-foreground">
        {novelty.title}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{novelty.why}</p>
      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" onClick={onTour}>
          Przeklikaj · {novelty.steps.length}{" "}
          {novelty.steps.length > 4 ? "kroków" : "kroki"}
        </Button>
        <button
          type="button"
          onClick={onLater}
          className="ml-auto text-xs font-semibold text-muted-foreground hover:text-foreground"
        >
          Później
        </button>
      </div>
      <p className="mt-2 border-t border-border pt-2 text-[11px] text-muted-foreground">
        Zaliczysz też bez przeklikania — wystarczy, że raz użyjesz tej funkcji w
        pracy.
      </p>
    </div>
  );
}

function formatShipped(iso: string): string {
  const [, month, day] = iso.split("-");
  return `${day}.${month}`;
}

// Krok `ack` stoi nad otwartym oknem Radix (np. „Zakończ współpracę”), które
// wyłącza kliknięcia poza sobą (`pointer-events: none` na body) — karta
// przywraca je sobie. Klik w nią zamyka to okno bez zapisu, i o to chodzi.
function TourStepCard({
  novelty,
  state,
  box,
  blocked,
  onAck,
  onStop,
  onReveal,
}: {
  novelty: Novelty;
  state: TourState;
  box: Box | null;
  blocked: BoxState | null;
  onAck: () => void;
  onStop: () => void;
  onReveal: () => void;
}) {
  const step = novelty.steps[state.step];
  // Krok bez miejsca na ekranie przez 2 s (pusta tablica, brak rekrutacji,
  // przycisk tylko dla części osób) da się minąć. Start i obowiązkowe okno
  // nowości nie mogą nikogo zatrzymać na zawsze (Artur, 30.10.2026); 2 s, żeby
  // nikt nie minął kroku, zanim ekran się wczyta.
  const [missingLong, setMissingLong] = useState(false);
  const hasBox = box !== null;
  useEffect(() => {
    setMissingLong(false);
    if (hasBox) return;
    const id = window.setTimeout(() => setMissingLong(true), 2000);
    return () => window.clearTimeout(id);
  }, [hasBox, state.step]);
  const style: React.CSSProperties = box
    ? placeBeside(box, STEP_CARD, {
        width: window.innerWidth,
        height: window.innerHeight,
      })
    : { bottom: 24, left: "50%", transform: "translateX(-50%)" };
  return (
    <div
      className="pointer-events-auto fixed z-[121] w-[340px] rounded-xl border border-primary/30 bg-card p-4 shadow-xl"
      style={style}
      role="status"
      data-testid="novelty-tour-step"
    >
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-primary">
        <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
        {novelty.start ? "Start w NEXUSIE" : "Przeklikaj nowość"} · krok{" "}
        {state.step + 1} z {novelty.steps.length}
        <span className="ml-auto flex gap-1" aria-hidden="true">
          {novelty.steps.map((s, i) => (
            <span
              key={s.anchor}
              className={`h-1.5 w-4 rounded-full ${i <= state.step ? "bg-primary" : "bg-border"}`}
            />
          ))}
        </span>
      </div>
      <p className="text-sm font-semibold text-foreground">{step.text}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {box
          ? step.hint
          : blocked === "covered"
            ? "To miejsce zasłania otwarty panel. Zamknij go, a krok wróci."
            : blocked === "offscreen"
              ? "To miejsce jest poza widokiem."
              : `Nie widzę tego miejsca na tym ekranie. Przejdź do: ${novelty.where} — przeklikanie poczeka.`}
      </p>
      <div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted-foreground">
        {blocked === "offscreen" ? (
          <Button size="sm" onClick={onReveal}>
            Pokaż to miejsce
          </Button>
        ) : step.ack ? (
          <Button size="sm" onClick={onAck}>
            Rozumiem
          </Button>
        ) : !box && missingLong ? (
          <Button size="sm" variant="outline" onClick={onAck}>
            Nie mam tego — dalej
          </Button>
        ) : (
          <span>Krok przejdzie sam, gdy klikniesz podświetlone miejsce.</span>
        )}
        <button
          type="button"
          onClick={onStop}
          className="shrink-0 font-semibold hover:text-foreground"
        >
          Przerwij
        </button>
      </div>
    </div>
  );
}

// Podświetlenie i karta kroku leżą nad oknami (z-110, `ui/dialog.tsx`), bo
// krok bywa w środku okna („Co z umową B2B?”). Kropka i karta nowości — pod.
function Spotlight({ box }: { box: Box }) {
  return (
    <div
      className="pointer-events-none fixed inset-0 z-[120]"
      aria-hidden
      data-testid="novelty-spotlight"
    >
      {/* Ramka w tym samym `boxShadow` co przyciemnienie: klasa `ring-*` też
          ustawia `box-shadow`, więc styl inline ją zjadał i ramki nie było. */}
      <div
        className="absolute rounded-lg transition-all duration-200 motion-reduce:transition-none"
        style={{
          top: box.top,
          left: box.left,
          width: box.width,
          height: box.height,
          boxShadow:
            "0 0 0 3px hsl(var(--primary)), 0 0 0 9999px rgb(0 0 0 / 0.45)",
        }}
      />
    </div>
  );
}

function FinishedCard({
  novelty,
  onClose,
}: {
  novelty: Novelty;
  onClose: () => void;
}) {
  return (
    <div
      className="pointer-events-auto fixed bottom-6 left-1/2 z-[121] w-[380px] max-w-[calc(100vw-24px)] -translate-x-1/2 rounded-xl border border-success/30 bg-card p-4 shadow-xl"
      role="status"
      data-testid="novelty-tour-finished"
    >
      <div className="flex items-start gap-3">
        <CheckCircle2
          className="mt-0.5 h-5 w-5 shrink-0 text-success"
          aria-hidden="true"
        />
        <div className="min-w-0">
          <p className="text-sm font-semibold">Zaliczone: {novelty.title}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {novelty.start
              ? "Postęp masz na liście Startu. Zaliczenie widzi też Twój Head of Recruitment."
              : "Kropka zniknęła. Zaliczenie widzi też Twój Head of Recruitment."}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Zamknij"
          className="text-muted-foreground hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

/** „2 kroki”, „5 kroków” — polska odmiana dla 2–6 kroków przeklikania. */
function stepsLabel(count: number): string {
  return `${count} ${count >= 2 && count <= 4 ? "kroki" : "kroków"}`;
}

function ProcessDialog({
  novelty,
  onTour,
  onPostpone,
  postponeError,
}: {
  novelty: Novelty;
  onTour: () => void;
  onPostpone: () => void;
  postponeError: string | null;
}) {
  return (
    <Dialog open onOpenChange={() => undefined}>
      <DialogContent
        hideClose
        className="max-w-lg"
        onEscapeKeyDown={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>
            {novelty.tier === "process" ? "Zmiana w procesie" : "Nowe w NEXUSIE"}:{" "}
            {novelty.title}
          </DialogTitle>
          <DialogDescription>
            Przeklikaj raz, żeby wiedzieć, jak z tego korzystać. Odłożyć możesz
            jeden raz — do jutra rano.
          </DialogDescription>
        </DialogHeader>
        <div className="relative space-y-3 px-6 py-4 text-sm">
          <div className="rounded-lg border border-warning/25 bg-warning-muted p-3 text-warning-muted-foreground">
            {novelty.why}
          </div>
          <p className="text-muted-foreground">
            Przeklikanie ma {stepsLabel(novelty.steps.length)} na prawdziwym
            ekranie
            {novelty.tier === "process"
              ? " i kończy się przed zapisem — niczego nie zmienisz naprawdę."
              : "."}
          </p>
          {postponeError ? (
            <p className="text-destructive">{postponeError}</p>
          ) : null}
        </div>
        <DialogFooter className="flex items-center gap-2 sm:justify-between">
          {novelty.can_postpone ? (
            <button
              type="button"
              onClick={onPostpone}
              className="inline-flex items-center gap-1 text-xs font-semibold text-muted-foreground hover:text-foreground"
            >
              <Clock className="h-3.5 w-3.5" aria-hidden="true" />
              Przypomnij jutro rano (raz)
            </button>
          ) : (
            <span />
          )}
          <Button size="sm" onClick={onTour}>
            Przeklikaj teraz
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function NoveltyLayer() {
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const novelties = useMyNovelties(
    hydrated && Boolean(user) && user?.role !== "trainee",
  );
  const sendEvent = useNoveltyEvent();

  const [tour, setTour] = useState<TourState | null>(null);
  const [finished, setFinished] = useState<Novelty | null>(null);
  const [openCard, setOpenCard] = useState<string | null>(null);
  const [hiddenCards, setHiddenCards] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [postponeError, setPostponeError] = useState<string | null>(null);
  const unsolicitedShown = useRef<Set<string>>(new Set());

  useEffect(() => {
    setTour(readTour());
    const onStart = () => setTour(readTour());
    window.addEventListener(NOVELTY_TOUR_START_EVENT, onStart);
    return () => window.removeEventListener(NOVELTY_TOUR_START_EVENT, onStart);
  }, []);

  const byId = useMemo(
    () => new Map(novelties.map((n) => [n.id, n])),
    [novelties],
  );
  const touring = tour ? (byId.get(tour.noveltyId) ?? null) : null;
  const dots = dotNovelties(novelties);
  const anchors = useMemo(() => {
    const list = dots.map((n) => n.dot_anchor);
    if (touring && tour) list.push(touring.steps[tour.step]?.anchor ?? "");
    return [...new Set(list.filter(Boolean))];
  }, [dots, touring, tour]);
  const stepAnchor =
    touring && tour ? (touring.steps[tour.step]?.anchor ?? null) : null;
  const boxes = useAnchorBoxes(anchors, stepAnchor);

  // `seen` raz na kartę przeglądarki, gdy kropka pierwszy raz stanie na ekranie.
  useEffect(() => {
    for (const n of dots) {
      if (boxes.get(n.dot_anchor)?.state === "visible" && markSeenOnce(n.id))
        void sendEvent(n.id, "seen");
    }
  }, [boxes, dots, sendEvent]);

  // Podwójny klik w ostatni krok nie wysyła „toured” dwa razy.
  const finishing = useRef<string | null>(null);
  const finishTour = useCallback(
    (novelty: Novelty) => {
      if (finishing.current === novelty.id) return;
      finishing.current = novelty.id;
      writeTour(null);
      setTour(null);
      setFinished(novelty);
      void sendEvent(novelty.id, "toured");
    },
    [sendEvent],
  );

  // Jedno nasłuchiwanie kliknięć: krok przeklikania, użycie w pracy, drobiazg.
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (touring && tour) {
        const next = advanceTour(touring, tour, event.target);
        if (next === "finished")
          window.setTimeout(() => finishTour(touring), 250);
        else if (next) {
          writeTour(next);
          window.setTimeout(() => setTour(next), 250);
        }
      }
      for (const n of novelties) {
        if (touring?.id === n.id) continue;
        const e = eventForClick(n, event.target);
        if (e) void sendEvent(n.id, e);
      }
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [novelties, touring, tour, finishTour, sendEvent]);

  const startTour = (novelty: Novelty) => {
    const state = { noveltyId: novelty.id, step: 0 };
    finishing.current = null;
    writeTour(state);
    setTour(state);
    setOpenCard(null);
    setPostponeError(null);
  };

  // Ekran, na którym osoba przerwała albo odłożyła obowiązkowe okno — do
  // wyjścia z niego okno nie wraca (inaczej „Przerwij” od razu by je otworzył).
  const [quietPath, setQuietPath] = useState<string | null>(null);

  const stopTour = () => {
    writeTour(null);
    setTour(null);
    setQuietPath(pathname);
  };

  // Lista Startu sama pokazuje ✓ — karta „Zaliczone” zasłaniałaby przy
  // 1280 × 720 przycisk ostatniej pozycji.
  const showFinished =
    finished !== null && !(finished.start && pathname.startsWith(START_PATH));

  // Przeklikanie nowości, której już nie ma na liście (zaliczona gdzie indziej) — koniec.
  useEffect(() => {
    if (tour && novelties.length > 0 && !byId.has(tour.noveltyId)) {
      writeTour(null);
      setTour(null);
    }
  }, [tour, novelties, byId]);

  if (!user || novelties.length === 0)
    return showFinished ? (
      <FinishedCard novelty={finished} onClose={() => setFinished(null)} />
    ) : null;

  if (touring && tour && touring.steps[tour.step]) {
    const measured = boxes.get(touring.steps[tour.step].anchor) ?? null;
    const box = measured?.state === "visible" ? measured : null;
    return (
      <>
        {/* Postać „Moi ludzie” z dymkiem w rogu zasłania stopkę panelu
            (np. „Zakończ współpracę…”) — na czas przeklikania jej nie ma. */}
        <style>{"[data-floating-corner]{visibility:hidden}"}</style>
        {box ? <Spotlight box={box} /> : null}
        <TourStepCard
          novelty={touring}
          state={tour}
          box={box}
          blocked={measured && !box ? measured.state : null}
          onStop={stopTour}
          onReveal={() => revealAnchor(touring.steps[tour.step].anchor)}
          onAck={() => {
            const next = acknowledgeStep(touring, tour);
            if (next === "finished") finishTour(touring);
            else {
              writeTour(next);
              setTour(next);
            }
          }}
        />
      </>
    );
  }

  const required =
    quietPath === pathname ? null : requiredForPath(novelties, pathname);
  if (required) {
    return (
      <ProcessDialog
        novelty={required}
        postponeError={postponeError}
        onTour={() => {
          startTour(required);
          if (!pathname.startsWith(required.href)) router.push(required.href);
        }}
        onPostpone={async () => {
          const ok = await sendEvent(required.id, "postponed");
          if (ok) setQuietPath(pathname);
          setPostponeError(
            ok
              ? null
              : "Nie udało się odłożyć. Przeklikaj teraz albo spróbuj za chwilę.",
          );
        }}
      />
    );
  }

  const visible = new Set(
    [...boxes].filter(([, b]) => b.state === "visible").map(([a]) => a),
  );
  const solicited = openCard ? (byId.get(openCard) ?? null) : null;
  let card = solicited && visible.has(solicited.dot_anchor) ? solicited : null;
  if (!card) {
    const candidate = cardCandidate(
      novelties.filter((n) => !hiddenCards.has(n.id)),
      visible,
    );
    if (
      candidate &&
      (unsolicitedShown.current.has(candidate.id) ||
        (!modalOpen() && canShowUnsolicited(user.id)))
    ) {
      if (!unsolicitedShown.current.has(candidate.id)) {
        unsolicitedShown.current.add(candidate.id);
        recordUnsolicited(user.id);
      }
      card = candidate;
    }
  }

  return (
    <>
      {dots.map((n) => {
        const box = boxes.get(n.dot_anchor);
        if (box?.state !== "visible") return null;
        return (
          <Dot
            key={n.id}
            box={box}
            label={n.title}
            onClick={n.tier === "dot" ? undefined : () => setOpenCard(n.id)}
          />
        );
      })}
      {card ? (
        <NoveltyCard
          novelty={card}
          box={boxes.get(card.dot_anchor)!}
          onTour={() => startTour(card!)}
          onLater={() => {
            setHiddenCards((prev) => new Set([...prev, card!.id]));
            setOpenCard(null);
            void sendEvent(card!.id, "card_dismissed");
          }}
        />
      ) : null}
      {showFinished ? (
        <FinishedCard novelty={finished} onClose={() => setFinished(null)} />
      ) : null}
    </>
  );
}
