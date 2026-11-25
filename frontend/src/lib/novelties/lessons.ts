/**
 * Lekcje nowości (decyzje Artura 23.11.2026, `docs/claude/ui/nowosci-do-przeklikania.md`).
 *
 * Przeklikanie nie uczyło (mediana 12 s na nowość), więc nowość przechodzi się
 * w lekcji na Poligonie, w trzech etapach:
 * 1. pokaz — kroki wpisów z podświetleniem (`NoveltyLayer`), wpis po wpisie;
 * 2. sam — to samo bez podświetlenia; zalicza warunek `check` (`LessonLayer`);
 * 3. pytanie „po co / kiedy”; dwa razy źle z rzędu → z powrotem do pokazu.
 *
 * Stan przebiegu żyje w `sessionStorage` tej karty, razem z treścią lekcji,
 * bo przejścia między ekranami Poligonu przeładowują stronę.
 */

import { enterPoligon, leavePoligon } from "@/lib/poligon/mode";
import type { PoligonAction } from "@/lib/poligon/store";

import { sendLessonEvent } from "./api";
import { DAILY_PATH, withSteps } from "./daily";
import { withinAnchor, writeTour, type Novelty } from "./logic";

export type LessonCheck =
  | { kind: "click"; anchor: string }
  | { kind: "move"; to: string; reason_includes?: string | null; feedback: string }
  | { kind: "page"; path_prefix: string; query: Record<string, string> };

export interface LessonQuestion {
  q: string;
  options: string[];
  /** Indeks dobrej odpowiedzi w `options`. */
  answer: number;
  explain: string;
}

export type LessonState = "todo" | "shown" | "retry" | "done";
export type ReviewState = "todo" | "passed" | "failed";

export interface Lesson {
  id: string;
  title: string;
  task: string;
  solo_href: string;
  check: LessonCheck;
  questions: LessonQuestion[];
  shipped_on: string;
  novelties: Novelty[];
  state: LessonState;
  solo_failed_count: number;
  /** Powtórka piątkowa: od razu etap „sam”, bez pytania. */
  review: boolean;
  review_state: ReviewState | null;
  /** Szkolenia: wszystkie wpisy lekcji przeklikane przed 23.11.2026. */
  legacy_done?: boolean;
}

export type LessonStage = "show" | "solo" | "quiz";
export type LessonOrigin = "daily" | "trainings";

export const TRAININGS_NOVELTIES_PATH = "/trainings?tab=nowosci";

export interface LessonRun {
  lesson: Pick<Lesson, "id" | "title" | "task" | "solo_href" | "check" | "questions">;
  /** Wpisy pokazu w kolejności, już z krokami (`withSteps`). */
  show: Novelty[];
  stage: LessonStage;
  /** Który wpis pokazu trwa. */
  showIndex: number;
  review: boolean;
  origin: LessonOrigin;
  /** Bieżące pytanie (indeks w `lesson.questions`). */
  question: number;
  /** Złe odpowiedzi z rzędu — druga wraca do pokazu. */
  wrongStreak: number;
}

const RUN_KEY = "nexus:lesson-run:v1";
export const LESSON_RUN_EVENT = "nexus:lesson-run";

export function readRun(): LessonRun | null {
  try {
    const raw = window.sessionStorage.getItem(RUN_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LessonRun>;
    return parsed && parsed.lesson && Array.isArray(parsed.show) && parsed.stage
      ? (parsed as LessonRun)
      : null;
  } catch {
    return null;
  }
}

export function writeRun(run: LessonRun | null): void {
  try {
    if (run === null) window.sessionStorage.removeItem(RUN_KEY);
    else window.sessionStorage.setItem(RUN_KEY, JSON.stringify(run));
  } catch {
    /* storage zablokowany — lekcja potrwa do przeładowania strony */
  }
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(LESSON_RUN_EVENT));
}

/** Wpisy pokazu: tylko te z krokami (drobiazg bez kroków dostaje krok na kropce). */
export function showNovelties(lesson: Pick<Lesson, "novelties">): Novelty[] {
  return lesson.novelties.map(withSteps).filter((n) => n.steps.length > 0);
}

export function practiceHref(novelty: Novelty): string {
  return novelty.practice_href ?? novelty.href;
}

export function originPath(origin: LessonOrigin): string {
  return origin === "trainings" ? TRAININGS_NOVELTIES_PATH : DAILY_PATH;
}

/** Stan przebiegu na starcie: od pokazu albo od razu „sam” (po pokazie, powtórka). */
export function initialRun(
  lesson: Lesson,
  origin: LessonOrigin,
  opts: { solo?: boolean } = {},
): LessonRun {
  const show = showNovelties(lesson);
  const solo = Boolean(opts.solo || lesson.review) || show.length === 0;
  return {
    lesson: {
      id: lesson.id,
      title: lesson.title,
      task: lesson.task,
      solo_href: lesson.solo_href,
      check: lesson.check,
      questions: lesson.questions,
    },
    show,
    stage: solo ? "solo" : "show",
    showIndex: 0,
    review: lesson.review,
    origin,
    question: 0,
    wrongStreak: 0,
  };
}

/** Pokaz od pierwszego wpisu — na starcie i po „Pokaż jeszcze raz”. */
export function restartShow(run: LessonRun): LessonRun {
  return { ...run, stage: run.show.length > 0 ? "show" : "solo", showIndex: 0, wrongStreak: 0 };
}

/** Ekran, na który prowadzi etap, i ustawienie przeklikania dla pokazu. */
export function stageHref(run: LessonRun): string {
  if (run.stage === "show") {
    const novelty = run.show[run.showIndex];
    if (novelty) return practiceHref(novelty);
  }
  return run.lesson.solo_href;
}

/** Wejście w etap: zapis stanu, przeklikanie wpisu pokazu i ekran Poligonu. */
export function goToStage(run: LessonRun): void {
  writeRun(run);
  const novelty = run.stage === "show" ? run.show[run.showIndex] : null;
  writeTour(novelty ? { noveltyId: novelty.id, step: 0 } : null);
  enterPoligon(stageHref(run), "novelty");
}

export function startLesson(lesson: Lesson, origin: LessonOrigin, opts: { solo?: boolean } = {}): void {
  goToStage(initialRun(lesson, origin, opts));
}

/** Koniec przebiegu: tryb ćwiczebny zdjęty, powrót na listę, z której przyszła osoba. */
export function leaveLesson(run: LessonRun | null): void {
  writeRun(null);
  writeTour(null);
  leavePoligon(originPath(run?.origin ?? "daily"));
}

/**
 * Po ostatnim kroku wpisu pokazu: następny wpis albo etap „sam”.
 * Zwraca nowy stan i to, czy pokaz właśnie się skończył.
 */
export function afterShowNovelty(run: LessonRun): { run: LessonRun; showDone: boolean } {
  const next = run.showIndex + 1;
  if (next < run.show.length) return { run: { ...run, showIndex: next }, showDone: false };
  return { run: { ...run, stage: "solo", showIndex: 0 }, showDone: true };
}

export type SoloVerdict = { done: true } | { done: false; feedback: string } | null;

/** Ruch karty na Poligonie wobec warunku `move`; inne zdarzenia nie mają znaczenia. */
export function judgeMove(check: LessonCheck, action: PoligonAction): SoloVerdict {
  if (check.kind !== "move" || action.type !== "move") return null;
  if (action.toStage !== check.to) return { done: false, feedback: check.feedback };
  const want = check.reason_includes?.toLowerCase();
  if (want && !(action.rejectionReasonName ?? "").toLowerCase().includes(want)) {
    return { done: false, feedback: check.feedback };
  }
  return { done: true };
}

export function judgeClick(check: LessonCheck, target: EventTarget | null): boolean {
  return check.kind === "click" && withinAnchor(target, check.anchor);
}

export function judgePage(check: LessonCheck, pathname: string, search: string): boolean {
  if (check.kind !== "page") return false;
  // „/sales/companies/” = dowolna karta firmy pod tą ścieżką.
  const prefix = check.path_prefix.replace(/\/+$/, "");
  if (pathname !== prefix && !pathname.startsWith(`${prefix}/`)) return false;
  const params = new URLSearchParams(search);
  return Object.entries(check.query ?? {}).every(([key, value]) => params.get(key) === value);
}

/** Odpowiedzi w stałej, ale wymieszanej kolejności (zależnej od lekcji i pytania). */
export function shuffledOptions(
  lessonId: string,
  index: number,
  question: LessonQuestion,
): { text: string; correct: boolean }[] {
  const options = question.options.map((text, i) => ({ text, correct: i === question.answer }));
  let seed = 0;
  for (const ch of `${lessonId}:${index}`) seed = (seed * 31 + ch.charCodeAt(0)) >>> 0;
  for (let i = options.length - 1; i > 0; i -= 1) {
    seed = (seed * 1103515245 + 12345) >>> 0;
    const j = seed % (i + 1);
    [options[i], options[j]] = [options[j], options[i]];
  }
  return options;
}

/** Po złej odpowiedzi: drugie pytanie albo — przy drugiej złej z rzędu — powrót do pokazu. */
export function afterWrongAnswer(run: LessonRun): { run: LessonRun; backToShow: boolean } {
  const streak = run.wrongStreak + 1;
  if (streak >= 2) return { run: restartShow(run), backToShow: true };
  const next = (run.question + 1) % Math.max(1, run.lesson.questions.length);
  return { run: { ...run, question: next, wrongStreak: streak }, backToShow: false };
}

/** Miejsce w NEXUSIE wpisu słowami użytkownika — pierwszy człon „gdzie”. */
export function lessonArea(lesson: Pick<Lesson, "novelties">): string {
  return lesson.novelties[0]?.where.split("→")[0]?.trim() || "NEXUS";
}

/**
 * „Coś nie działa — zalicz i dalej” (Artur, 25.11.2026): zepsuty pokaz, zadanie
 * albo pytanie nie może nikogo zatrzymać. Serwer zalicza lekcję od razu
 * (zdarzenie `broken`) i zostawia ślad, która lekcja jest zepsuta. Bez
 * połączenia lekcja zostaje niezaliczona, ale osoba i tak wraca do listy.
 */
export async function skipBrokenLesson(run: LessonRun): Promise<boolean> {
  const ok = await sendLessonEvent(run.lesson.id, "broken");
  leaveLesson(run);
  return ok;
}
