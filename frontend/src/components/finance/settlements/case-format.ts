// Etykiety i kolory karty sprawy („Co dalej”) i listy spraw rozliczeń.
import type { CaseActor, CaseStep, CaseStepState } from "@/lib/api/settlement-cases";
import { countPl } from "@/lib/plural-pl";

import { shortDay } from "./format";

/** Kolor kroku z tokenów: zrobione, zaległe, dziś, najbliższy, dalszy. */
export const STEP_CLASS: Record<CaseStepState, string> = {
  done: "bg-success-muted text-success-muted-foreground",
  overdue: "bg-destructive-muted text-destructive-muted-foreground",
  today: "bg-warning-muted text-warning-muted-foreground",
  upcoming: "bg-info-muted text-info-muted-foreground",
  planned: "bg-muted text-muted-foreground",
};

export const ACTOR_FILTERS: { key: "all" | CaseActor; label: string }[] = [
  { key: "all", label: "Wszyscy" },
  { key: "consultant", label: "Konsultant" },
  { key: "client", label: "Akceptujący u klienta" },
  { key: "dl", label: "Delivery Lead" },
  { key: "finance", label: "Finanse" },
];

export function overdueText(days: number): string {
  return `zaległe ${countPl(days, "dzień rob.", "dni rob.", "dni rob.")}`;
}

/**
 * Kiedy krok: data zrobienia z osobą, zaległość, „dziś” albo termin.
 * `brief` (pasek terminów) bez liczby dni — tę mówi „Teraz”.
 */
export function stepWhen(step: CaseStep, overdueDays: number, brief = false): string {
  if (step.state === "done") {
    return [shortDay(step.done_on), step.done_by, step.note].filter(Boolean).join(" · ");
  }
  if (step.state === "overdue") {
    return brief ? `${shortDay(step.due)} · zaległe` : `od ${shortDay(step.due)}, ${overdueText(Math.max(overdueDays, 1))}`;
  }
  if (step.state === "today") return "dziś";
  return shortDay(step.due);
}

/** Jedna linia o bieżącym kroku do listy spraw i nagłówka sprawy. */
export function nowText(step: CaseStep | null, overdueDays: number): string {
  if (!step) return "Wszystkie kroki zrobione: czekamy na poprawkę";
  return `${step.label}: ${stepWhen(step, overdueDays)}`;
}
