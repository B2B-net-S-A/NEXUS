"use client";

/**
 * Nowości do przeklikania — przeklikanie nad prawdziwym ekranem
 * (`docs/claude/ui/nowosci-do-przeklikania.md`).
 *
 * Od 18.11.2026 (decyzja Artura) w ciągu dnia nic nie wyskakuje: bez kropek,
 * kart i okien. Nowości przeklikuje się rano w porcji (`/nowosci-dnia`) —
 * na rekrutacji ćwiczebnej Poligonu, więc kliknięcie niczego nie zapisze —
 * a Start w NEXUSIE z `/start`. Warstwa prowadzi tylko przeklikanie:
 * podświetlony prawdziwy element, krok przechodzi po jego kliknięciu (krok
 * `ack` — przyciskiem „Rozumiem”), także po przejściu na inny ekran.
 *
 * Od 23.11.2026 to samo przeklikanie jest pokazem w lekcji nowości
 * (`lib/novelties/lessons.ts`): wpis po wpisie, bez zaliczania nowości;
 * po ostatnim wpisie lekcja przechodzi do etapu „sam” (`LessonLayer`).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { CheckCircle2, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  sendLessonEvent,
  useDailyStatus,
  useMyNoveltiesState,
  useNoveltyEvent,
} from "@/lib/novelties/api";
import {
  afterShowNovelty,
  goToStage,
  LESSON_RUN_EVENT,
  leaveLesson,
  readRun,
  type LessonRun,
} from "@/lib/novelties/lessons";
import { DAILY_PATH, withSteps } from "@/lib/novelties/daily";
import {
  acknowledgeStep,
  anchorSelector,
  advanceTour,
  intersectRects,
  keepDialogsOpenIf,
  nextStepInSameDialog,
  onEveryClick,
  placeBeside,
  readTour,
  START_PATH,
  TOUR_STEP_CARD,
  writeTour,
  type Novelty,
  type Rect,
  type TourState,
} from "@/lib/novelties/logic";
import {
  enterPoligon,
  isNoveltyPractice,
  leavePoligon,
} from "@/lib/poligon/mode";
import { useAuthStore } from "@/store/auth";

export const NOVELTY_TOUR_START_EVENT = "nexus:novelty-tour-start";

/** Start przeklikania na bieżącej karcie (Start w NEXUSIE). */
export function startNoveltyTour(noveltyId: string): void {
  writeTour({ noveltyId, step: 0 });
  window.dispatchEvent(new CustomEvent(NOVELTY_TOUR_START_EVENT));
}

/**
 * Przeklikanie nowości na Poligonie (18.11.2026): tryb ćwiczebny na tej
 * karcie, ekran `practice_href` (element na rekrutacji ćwiczebnej) albo
 * `href`. Zapisy są tam wyłączone, więc nowość można klikać naprawdę.
 */
export function startNoveltyPractice(novelty: Novelty): void {
  writeTour({ noveltyId: novelty.id, step: 0 });
  enterPoligon(novelty.practice_href ?? novelty.href, "novelty");
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

// Krok `ack` stoi nad otwartym oknem Radix (np. „Zakończ współpracę”), które
// wyłącza kliknięcia poza sobą (`pointer-events: none` na body) — karta
// przywraca je sobie. Klik w nią zamyka to okno bez zapisu, i o to chodzi,
// chyba że następny krok stoi w tym samym oknie: wtedy okno zostaje
// (24.11.2026, „Co zmienił klient?”: po „Rozumiem” przy polu treści krok
// „Przygotuj zmiany” nie miał czego wskazać).
function TourStepCard({
  novelty,
  state,
  box,
  blocked,
  lessonLabel,
  onAck,
  onStop,
  onReveal,
}: {
  novelty: Novelty;
  state: TourState;
  box: Box | null;
  blocked: BoxState | null;
  /** Pokaz w lekcji: „Lekcja · pokaz 1 z 2”, zamiast „Nowość”. */
  lessonLabel: string | null;
  onAck: () => void;
  onStop: () => void;
  onReveal: () => void;
}) {
  const step = novelty.steps[state.step];
  const nextAnchor = novelty.steps[state.step + 1]?.anchor ?? null;
  const keepDialogForNextStep = useMemo(
    () => keepDialogsOpenIf(() => nextStepInSameDialog(step.anchor, nextAnchor)),
    [step.anchor, nextAnchor],
  );
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
    ? placeBeside(box, TOUR_STEP_CARD, {
        width: window.innerWidth,
        height: window.innerHeight,
      })
    : { bottom: 24, left: "50%", transform: "translateX(-50%)" };
  return (
    <div
      ref={keepDialogForNextStep}
      className="pointer-events-auto fixed z-[121] w-[340px] rounded-xl border border-primary/30 bg-card p-4 shadow-xl"
      style={style}
      role="status"
      data-testid="novelty-tour-step"
    >
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-primary">
        <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
        {lessonLabel ?? (novelty.start ? "Start w NEXUSIE" : "Nowość")} · krok{" "}
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
            ? "To miejsce coś zasłania (otwarty panel albo pasek u dołu). Kliknij „Pokaż to miejsce” albo zamknij panel."
            : blocked === "offscreen"
              ? "To miejsce jest poza widokiem."
              : step.ack
                ? // Krok „Rozumiem” (np. drobiazg z porcji) bez elementu na
                  // ekranie: treść wystarcza, nie odsyłamy z rekrutacji ćwiczebnej.
                  `${step.hint} Tutaj tego miejsca nie widać — znajdziesz je w: ${novelty.where}.`
                : `Nie widzę tego miejsca na tym ekranie. Przejdź do: ${novelty.where} — przeklikanie poczeka.`}
      </p>
      <div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted-foreground">
        {blocked === "offscreen" || blocked === "covered" ? (
          // Zasłonięte bywa przez przyklejony pasek u dołu formularza (25.11.2026:
          // „Stanowisko w zespole” pod paskiem „Brakuje 12 rzeczy” przy 1280 × 720)
          // — przewinięcie na środek ekranu je odsłania.
          <span className="flex items-center gap-2">
            <Button size="sm" onClick={onReveal}>
              Pokaż to miejsce
            </Button>
            {blocked === "covered" && missingLong ? (
              <Button size="sm" variant="outline" onClick={onAck}>
                Nie mam tego — dalej
              </Button>
            ) : null}
          </span>
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
      {/* Bez „Coś nie działa” w pokazie (Artur, 26.11.2026): przycisk od
          pierwszego kroku służył do pomijania całych porcji. Zepsuty krok
          ratuje „Nie mam tego — dalej”, a furtka czeka w zadaniu i pytaniu. */}
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
          <p className="text-sm font-semibold">
            {novelty.start ? "Zaliczone" : "Koniec pokazu"}: {novelty.title}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {novelty.start
              ? "Postęp masz na liście Startu. Zaliczenie widzi też Twój Head of Recruitment."
              : "Zalicza ją lekcja w porannych nowościach. Wracamy do listy."}
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

export function NoveltyLayer() {
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const pathname = usePathname() ?? "";
  const enabled = hydrated && Boolean(user) && user?.role !== "trainee";
  const mine = useMyNoveltiesState(enabled);
  const novelties = mine.items;
  const daily = useDailyStatus(enabled);
  const sendEvent = useNoveltyEvent();

  const [tour, setTour] = useState<TourState | null>(null);
  const [finished, setFinished] = useState<Novelty | null>(null);
  const [run, setRun] = useState<LessonRun | null>(null);

  useEffect(() => {
    setTour(readTour());
    setRun(readRun());
    const onStart = () => setTour(readTour());
    const onRun = () => setRun(readRun());
    window.addEventListener(NOVELTY_TOUR_START_EVENT, onStart);
    window.addEventListener(LESSON_RUN_EVENT, onRun);
    return () => {
      window.removeEventListener(NOVELTY_TOUR_START_EVENT, onStart);
      window.removeEventListener(LESSON_RUN_EVENT, onRun);
    };
  }, []);
  /** Pokaz w lekcji: przeklikanie wpisów lekcji, bez zaliczania nowości. */
  const showing = run?.stage === "show" ? run : null;

  // Porcja bywa starsza niż 45 dni życia nowości (po urlopie), więc jej
  // pozycje dochodzą do listy z `/mine`.
  const byId = useMemo(
    () =>
      new Map(
        [...novelties, ...(daily?.items ?? []), ...(showing?.show ?? [])].map(
          (n) => [n.id, withSteps(n)],
        ),
      ),
    [novelties, daily, showing],
  );
  // Obie listy muszą przyjść, zanim uznamy przeklikanie za nieaktualne: po
  // przeładowaniu w tryb ćwiczebny `/mine` bywa pierwszy, a pozycji porcji
  // starszej niż 45 dni w nim nie ma (recenzja 18.11.2026).
  const loaded = (mine.loaded && daily !== null) || showing !== null;
  const touring = tour ? (byId.get(tour.noveltyId) ?? null) : null;
  const stepAnchor =
    touring && tour ? (touring.steps[tour.step]?.anchor ?? null) : null;
  const anchors = useMemo(
    () => (stepAnchor ? [stepAnchor] : []),
    [stepAnchor],
  );
  const boxes = useAnchorBoxes(anchors, stepAnchor);

  // Przeklikanie z porcji idzie na Poligonie; po nim wracamy do listy porcji
  // (przeładowanie zdejmuje tryb ćwiczebny z tej karty).
  const backToDaily = useCallback(() => {
    if (isNoveltyPractice()) leavePoligon(DAILY_PATH);
  }, []);

  // Podwójny klik w ostatni krok nie wysyła „toured” dwa razy.
  const finishing = useRef<string | null>(null);
  const finishTour = useCallback(
    async (novelty: Novelty) => {
      if (finishing.current === novelty.id) return;
      finishing.current = novelty.id;
      writeTour(null);
      setTour(null);
      const lesson = readRun();
      if (lesson?.stage === "show" && lesson.show[lesson.showIndex]?.id === novelty.id) {
        // Pokaz nie zalicza nowości — zalicza ją dopiero cała lekcja.
        const next = afterShowNovelty(lesson);
        // Nieudany zapis pokazu wyjdzie przy „sam” (serwer odmówi bez pokazu)
        // i karta zadania powie, że postęp się nie zapisał.
        if (next.showDone) await sendLessonEvent(lesson.lesson.id, "shown");
        goToStage(next.run);
        return;
      }
      setFinished(novelty);
      // Przeklikanie na Poligonie poza lekcją (powtórka z archiwum ✦) niczego
      // nie zalicza — nowość zalicza tylko lekcja (23.11.2026). Start w NEXUSIE
      // idzie po prawdziwych ekranach i zalicza się jak dotąd.
      if (isNoveltyPractice()) {
        window.setTimeout(backToDaily, 900);
        return;
      }
      await sendEvent(novelty.id, "toured");
    },
    [sendEvent, backToDaily],
  );

  // Krok przechodzi po kliknięciu prawdziwego elementu.
  useEffect(() => {
    if (!touring || !tour) return;
    const onClick = (target: EventTarget | null) => {
      const next = advanceTour(touring, tour, target);
      if (next === "finished")
        window.setTimeout(() => void finishTour(touring), 250);
      else if (next) {
        writeTour(next);
        window.setTimeout(() => setTour(next), 250);
      }
    };
    return onEveryClick(document, onClick);
  }, [touring, tour, finishTour]);

  const stopTour = () => {
    writeTour(null);
    setTour(null);
    if (readRun()) {
      leaveLesson(readRun());
      return;
    }
    backToDaily();
  };

  // Lista Startu i lista porcji same pokazują ✓ — karta „Zaliczone”
  // zasłaniałaby przy 1280 × 720 przycisk ostatniej pozycji.
  const showFinished =
    finished !== null &&
    !(finished.start && pathname.startsWith(START_PATH)) &&
    !pathname.startsWith(DAILY_PATH);

  // Przeklikanie nowości, której już nie ma na liście — koniec.
  useEffect(() => {
    if (tour && loaded && !byId.has(tour.noveltyId)) {
      writeTour(null);
      setTour(null);
    }
  }, [tour, loaded, byId]);

  if (user && touring && tour && touring.steps[tour.step]) {
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
          lessonLabel={
            showing && showing.show[showing.showIndex]?.id === touring.id
              ? `Lekcja · pokaz${showing.show.length > 1 ? ` ${showing.showIndex + 1} z ${showing.show.length}` : ""}`
              : null
          }
          onStop={stopTour}
          onReveal={() => revealAnchor(touring.steps[tour.step].anchor)}
          onAck={() => {
            const next = acknowledgeStep(touring, tour);
            if (next === "finished") void finishTour(touring);
            else {
              writeTour(next);
              setTour(next);
            }
          }}
        />
      </>
    );
  }

  return showFinished ? (
    <FinishedCard novelty={finished} onClose={() => setFinished(null)} />
  ) : null;
}
