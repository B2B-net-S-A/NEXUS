/**
 * Lekcje nowości (23.11.2026): kotwice warunków istnieją we froncie, przebieg
 * pokaz → sam → pytanie i powrót do pokazu po dwóch złych odpowiedziach.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { groupLessons } from "@/components/trainings/NoveltyLessonsTab";
import {
  afterShowNovelty,
  afterWrongAnswer,
  initialRun,
  judgeMove,
  judgePage,
  restartShow,
  shuffledOptions,
  stageHref,
  type Lesson,
  type LessonCheck,
} from "@/lib/novelties/lessons";
import type { Novelty } from "@/lib/novelties/logic";
import type { PoligonAction } from "@/lib/poligon/store";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../../../../..");
const SRC = join(REPO, "frontend", "src");
const LESSONS = join(REPO, "backend", "app", "data", "novelties", "lessons.json");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (name === "__tests__" || name === "node_modules") return [];
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(tsx|ts)$/.test(name) ? [path] : [];
  });
}

function anchorsInSource(): Set<string> {
  const found = new Set<string>();
  for (const file of sourceFiles(SRC)) {
    for (const line of readFileSync(file, "utf8").split("\n")) {
      if (!line.includes("data-tour=") && !line.includes("data-help=")) continue;
      for (const m of line.matchAll(/"([a-z0-9][a-z0-9_-]*(?:\.[a-z0-9_-]+)+)"/g)) found.add(m[1]);
    }
  }
  return found;
}

function novelty(id: string, steps = 2, extra: Partial<Novelty> = {}): Novelty {
  return {
    id,
    title: `Wpis ${id}`,
    why: "Po co",
    tier: "dot",
    shipped_on: "2026-11-20",
    where: "Rekrutacja → Tablica",
    href: "/jobs",
    practice_href: `/jobs/990001?${id}=1`,
    dot_anchor: "jobs.list.scope",
    used_anchor: null,
    path_prefix: null,
    steps: Array.from({ length: steps }, (_, i) => ({ anchor: `a.${id}${i}`, text: "Krok", hint: "Podpowiedź", ack: false })),
    done: false,
    start: false,
    completed_via: null,
    show_card: false,
    required_now: false,
    can_postpone: false,
    ...extra,
  };
}

const QUESTIONS = [
  { q: "Pierwsze?", options: ["dobra", "zła 1", "zła 2"], answer: 0, explain: "Bo tak." },
  { q: "Drugie?", options: ["zła", "dobra", "zła 2"], answer: 1, explain: "Bo tak." },
];

function lesson(extra: Partial<Lesson> = {}): Lesson {
  return {
    id: "lekcja-test",
    title: "Lekcja",
    task: "Zrób to sam.",
    solo_href: "/jobs/990001",
    check: { kind: "click", anchor: "jobs.list.scope" },
    questions: QUESTIONS,
    shipped_on: "2026-11-20",
    novelties: [novelty("w1"), novelty("w2", 1)],
    state: "todo",
    solo_failed_count: 0,
    review: false,
    review_state: null,
    ...extra,
  };
}

describe("rejestr lekcji", () => {
  const registry = JSON.parse(readFileSync(LESSONS, "utf8")) as { id: string; check: LessonCheck }[];

  it("warunek „click” każdej lekcji to kotwica, która istnieje we froncie", () => {
    const source = anchorsInSource();
    const missing = registry
      .filter((l) => l.check.kind === "click")
      .map((l) => `${l.id}: ${(l.check as { anchor: string }).anchor}`)
      .filter((entry) => !source.has(entry.split(": ")[1]));
    expect(missing).toEqual([]);
  });
});

describe("przebieg lekcji", () => {
  it("zaczyna od pokazu pierwszego wpisu, a powtórka i „Teraz sam” od razu od zadania", () => {
    const run = initialRun(lesson(), "daily");
    expect(run.stage).toBe("show");
    expect(stageHref(run)).toBe("/jobs/990001?w1=1");
    expect(initialRun(lesson(), "daily", { solo: true }).stage).toBe("solo");
    expect(initialRun(lesson({ review: true }), "daily").stage).toBe("solo");
  });

  it("pokaz idzie wpis po wpisie, a po ostatnim przechodzi do zadania", () => {
    const first = afterShowNovelty(initialRun(lesson(), "daily"));
    expect(first.showDone).toBe(false);
    expect(first.run.showIndex).toBe(1);
    const last = afterShowNovelty(first.run);
    expect(last.showDone).toBe(true);
    expect(last.run.stage).toBe("solo");
    expect(stageHref(last.run)).toBe("/jobs/990001");
  });

  it("druga zła odpowiedź z rzędu wraca do pokazu od pierwszego wpisu", () => {
    const quiz = { ...initialRun(lesson(), "trainings"), stage: "quiz" as const };
    const once = afterWrongAnswer(quiz);
    expect(once.backToShow).toBe(false);
    expect(once.run.question).toBe(1);
    const twice = afterWrongAnswer(once.run);
    expect(twice.backToShow).toBe(true);
    expect(twice.run.stage).toBe("show");
    expect([twice.run.showIndex, twice.run.wrongStreak]).toEqual([0, 0]);
    // Po pokazie przyjdzie inne pytanie niż to, na którym poszło źle.
    expect(twice.run.question).toBe(once.run.question);
    expect(restartShow(quiz).stage).toBe("show");
  });

  it("odpowiedzi są wymieszane, ale stałe i z jedną dobrą", () => {
    const a = shuffledOptions("lekcja-test", 1, QUESTIONS[1]);
    expect(a).toEqual(shuffledOptions("lekcja-test", 1, QUESTIONS[1]));
    expect(a.filter((o) => o.correct)).toEqual([{ text: "dobra", correct: true }]);
    expect(a.map((o) => o.text).sort()).toEqual([...QUESTIONS[1].options].sort());
  });
});

describe("warunki zaliczenia", () => {
  const move = (toStage: string, reason: string | null = null): PoligonAction => ({
    type: "move",
    candidateId: 990105,
    fromStage: "screening",
    toStage,
    rejectionReasonId: null,
    rejectionReasonName: reason,
    rejectionNote: "",
    fixFields: [],
    clientRate: null,
  });
  const check: LessonCheck = { kind: "move", to: "withdrawn", reason_includes: "ofert", feedback: "Nie tu." };

  it("ruch do właściwego etapu z powodem zalicza, inny ruch daje podpowiedź, reszta milczy", () => {
    expect(judgeMove(check, move("withdrawn", "Przyjął inną ofertę"))).toEqual({ done: true });
    expect(judgeMove(check, move("rejected", "Przyjął inną ofertę"))).toEqual({ done: false, feedback: "Nie tu." });
    expect(judgeMove(check, move("withdrawn", "Stawka"))).toEqual({ done: false, feedback: "Nie tu." });
    expect(judgeMove(check, { type: "claim", candidateId: 1 })).toBeNull();
  });

  it("ekran z parametrem adresu; ukośnik na końcu to dowolna podstrona", () => {
    const page: LessonCheck = { kind: "page", path_prefix: "/sales/companies/", query: { tab: "contacts" } };
    expect(judgePage(page, "/sales/companies/42", "?tab=contacts")).toBe(true);
    expect(judgePage(page, "/sales/companies/42", "?tab=overview")).toBe(false);
    expect(judgePage(page, "/sales/leads", "?tab=contacts")).toBe(false);
  });
});

describe("Szkolenia → Nowości w NEXUSIE", () => {
  it("grupuje po miejscu, szuka w treści wpisów i filtruje nieumiane", () => {
    const sales = lesson({
      id: "lekcja-sprzedaz",
      title: "Mój dzień",
      novelties: [novelty("s1", 1, { where: "Sprzedaż → Mój dzień", why: "Własna data kroku" })],
      state: "done",
    });
    const groups = groupLessons([lesson(), sales], "", "all", new Date("2026-11-23T12:00:00Z"));
    expect(groups.map(([area]) => area).sort()).toEqual(["Rekrutacja", "Sprzedaż"]);
    expect(groupLessons([lesson(), sales], "data kroku", "all", new Date())[0][1][0].id).toBe("lekcja-sprzedaz");
    expect(groupLessons([lesson(), sales], "", "todo", new Date()).flatMap(([, l]) => l.map((x) => x.id))).toEqual([
      "lekcja-test",
    ]);
  });
});
