// Ćwiczenia Poligonu. Ćwiczenie zalicza zdarzenie (klik w kotwicę albo ruch na
// rekrutacji ćwiczebnej), nigdy przycisk „Rozumiem”. Informacja zwrotna to
// stałe reguły, bez modelu AI — każdy dostaje tę samą.

import type { PoligonAction } from "./store";

export interface ExerciseContext {
  /** Osoba z pierwszej kolumny, którą ćwiczenie każe przesunąć. */
  firstNew: { candidateId: number; fullName: string } | null;
}

export type Verdict = { done: true; tip?: string } | { done: false; feedback: string } | null;

export interface Exercise {
  id: string;
  module: string;
  title: (ctx: ExerciseContext) => string;
  task: (ctx: ExerciseContext) => string;
  hint: string;
  /** Ekran, na którym ćwiczenie się zaczyna. */
  href: string;
  /** Kotwica `data-tour` / `data-help`, którą pokazuje „Pokaż mi”. */
  anchor: string;
  /** Klik w kotwicę zalicza ćwiczenie. */
  doneOnClick?: boolean;
  /** Ocena zdarzenia z poligonu: zaliczone, podpowiedź albo nic. */
  judge?: (action: PoligonAction, ctx: ExerciseContext) => Verdict;
  /** Dobra praktyka pokazywana po zaliczeniu. */
  tip: string;
}

export const POLIGON_JOB_HREF = "/jobs/990001";
/** Kod etapu odrzuconych w szablonie rekrutacji. */
const REJECTED = "rejected";
const MIN_NOTE_LENGTH = 25;

export const LEVEL_1: readonly Exercise[] = [
  {
    id: "lista-zakres",
    module: "Lista rekrutacji",
    title: () => "Przełącz „Moje / Wszystkie”",
    task: () => "Kliknij przełącznik nad listą. „Moje” to rekrutacje, w których jesteś w zespole, „Wszystkie” — cała firma.",
    hint: "Przełącznik jest na górze listy, po lewej.",
    href: "/jobs",
    anchor: "jobs.list.scope",
    doneOnClick: true,
    tip: "Dzień zaczynasz od „Moich”. „Wszystkie” przydają się, gdy szukasz rekrutacji kolegi albo klienta.",
  },
  {
    id: "lista-filtry",
    module: "Lista rekrutacji",
    title: () => "Otwórz filtry",
    task: () => "Kliknij w pasek filtrów. Tu zawężasz listę do klienta, statusu i osób.",
    hint: "Pasek filtrów jest nad listą rekrutacji.",
    href: "/jobs",
    anchor: "jobs.list.filters",
    doneOnClick: true,
    tip: "Filtry zostają w adresie strony — link z filtrem możesz wysłać komuś z zespołu.",
  },
  {
    id: "lista-otworz",
    module: "Lista rekrutacji",
    title: () => "Otwórz rekrutację ĆW-01",
    task: () => "Wpisz w szukajkę „bankowość” albo „ĆW-01” i kliknij nazwę rekrutacji. Otworzy się jej Tablica.",
    hint: "Szukanie działa od razu, bez Entera.",
    href: "/jobs",
    anchor: "jobs.list.title",
    doneOnClick: true,
    tip: "Na Tablicy widzisz wszystkie osoby tej rekrutacji, podzielone na etapy.",
  },
  {
    id: "tablica-biore",
    module: "Tablica",
    title: () => "Weź osobę przyciskiem „Biorę”",
    task: () => "Kliknij „Biorę” na dowolnej karcie. Od teraz zespół widzi, że to Ty prowadzisz tę osobę.",
    hint: "„Biorę” jest w dolnym rogu karty.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.card",
    judge: (a) => (a.type === "claim" ? { done: true } : null),
    tip: "„Biorę” chroni przed tym, że dwie osoby dzwonią do tego samego kandydata.",
  },
  {
    id: "tablica-przesun",
    module: "Tablica",
    title: (ctx) => `Przesuń ${ctx.firstNew?.fullName ?? "osobę z „Nowych”"} na „Screening”`,
    task: (ctx) =>
      `Rozmowa telefoniczna poszła dobrze — ${ctx.firstNew?.fullName.split(" ")[0] ?? "ta osoba"} chce iść dalej. Przeciągnij kartę do kolumny „Screening” albo kliknij strzałkę → na karcie.`,
    hint: "Strzałka „dalej” jest w prawym dolnym rogu karty.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.card",
    judge: (a, ctx) => {
      if (a.type !== "move") return null;
      if (ctx.firstNew && a.candidateId !== ctx.firstNew.candidateId) {
        return { done: false, feedback: `Przesunęłaś inną osobę. W tym ćwiczeniu chodzi o ${ctx.firstNew.fullName} z kolumny „Nowi”.` };
      }
      if (a.toStage !== "screening") {
        return { done: false, feedback: "Karta pojechała na inny etap. Po pierwszej rozmowie osoba idzie na „Screening”." };
      }
      return { done: true };
    },
    tip: "Zanim przesuniesz osobę dalej, dopisz w panelu notatkę z rozmowy — Delivery Lead zobaczy, dlaczego ją prowadzisz. To jest następne ćwiczenie.",
  },
  {
    id: "panel-notatka",
    module: "Panel osoby",
    title: () => "Dodaj notatkę po rozmowie",
    task: () => "Kliknij kartę osoby, żeby otworzyć panel, i dodaj notatkę: co ustaliłaś (stawka, dostępność, motywacja).",
    hint: "Pole notatki jest na dole panelu osoby.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.person.note",
    judge: (a) => {
      if (a.type !== "note") return null;
      if (a.content.length < MIN_NOTE_LENGTH) {
        return { done: false, feedback: "Ta notatka jest za krótka, żeby zespół z niej skorzystał. Napisz pełnym zdaniem: stawka, od kiedy, dlaczego zmienia pracę." };
      }
      return { done: true };
    },
    tip: "Notatkę widzi cały zespół rekrutacji i każdy, kto otworzy profil osoby — także za pół roku.",
  },
  {
    id: "panel-odrzuc",
    module: "Panel osoby",
    title: () => "Odrzuć osobę z właściwym powodem",
    task: () => "W rozmowie padło 160 zł/h, a budżet to 115 zł/h. Otwórz panel osoby i odrzuć ją z powodem, który to opisuje.",
    hint: "„Odrzuć z powodem” jest w górnej części panelu osoby.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.person.actions",
    judge: (a) => {
      if (a.type !== "move" || a.toStage !== REJECTED) return null;
      const reason = (a.rejectionReasonName ?? "").toLowerCase();
      if (reason.includes("finans")) return { done: true };
      if (reason.startsWith("inne")) {
        return { done: false, feedback: "„Inne” to ostatnia deska ratunku: raporty i propozycje nie widzą, co było nie tak, nawet z opisem. Tu problemem była stawka — wybierz powód o oczekiwaniach finansowych i wpisz kwotę z rozmowy." };
      }
      return { done: false, feedback: `Wybrałaś „${a.rejectionReasonName ?? "inny powód"}”. Tu problemem była stawka — wybierz powód o oczekiwaniach finansowych.` };
    },
    tip: "Przy powodzie finansowym osoba wróci w propozycjach, gdy przyjdzie request z wyższą stawką.",
  },
];

export function exerciseCount(): number {
  return LEVEL_1.length;
}
