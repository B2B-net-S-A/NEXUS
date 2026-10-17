// Wejście konsultanta (etap 3, M6) — czyste funkcje zakładki „Wejście” kontraktu.

import {
  TASK_SOURCE_LABELS,
  type ContractEntryView,
  type EntryMissingReason,
  type LifecycleTask,
} from "@/lib/api/hr-lifecycle";
import { formatIsoDatePl } from "@/lib/date-pl";

/** Powód braku listy — z `not_yet` (start dalej niż 14 dni, lista powstanie sama). */
export type EntryReason = EntryMissingReason | "not_yet";

/**
 * Widok zakładki „Wejście” z polami po poprawkach etapu 3
 * (lustro `api/hr_lifecycle._entry_view`).
 */
export type EntryView = Omit<ContractEntryView, "missing_reason"> & {
  missing_reason: EntryReason | null;
  /** `not_yet`: dzień, od którego przegląd startów założy listę sam (`null` = już teraz). */
  auto_create_on?: string | null;
  /** Pakiet klienta nie wczytał się przy zakładaniu — jego pozycje dojdą później. */
  pack_failed?: boolean;
};

export interface EntryStep {
  key: "before" | "start" | "two_weeks" | "month" | "all";
  label: string;
  done: number;
  total: number;
}

const DAY_MS = 24 * 60 * 60 * 1000;

function dayNumber(iso: string): number {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return Date.UTC(year, month - 1, day) / DAY_MS;
}

function closed(task: LifecycleTask): boolean {
  return task.status !== "open";
}

/**
 * Kroki nad listą: „Przed startem”, „Dzień startu”, „Pierwsze 2 tygodnie”
 * (do 14 dni kalendarzowych po starcie), „Do 30 dni” (reszta i zadania bez
 * terminu). Zamknięte = zrobione albo pominięte.
 */
export function entrySteps(tasks: readonly LifecycleTask[], start: string | null): EntryStep[] {
  if (!start) {
    return [
      { key: "all", label: "Zadania", done: tasks.filter(closed).length, total: tasks.length },
    ];
  }
  const steps: EntryStep[] = [
    { key: "before", label: "Przed startem", done: 0, total: 0 },
    { key: "start", label: "Dzień startu", done: 0, total: 0 },
    { key: "two_weeks", label: "Pierwsze 2 tygodnie", done: 0, total: 0 },
    { key: "month", label: "Do 30 dni", done: 0, total: 0 },
  ];
  const anchor = dayNumber(start);
  for (const task of tasks) {
    const delta = task.due_date ? dayNumber(task.due_date) - anchor : Number.POSITIVE_INFINITY;
    const index = delta < 0 ? 0 : delta === 0 ? 1 : delta <= 14 ? 2 : 3;
    steps[index].total += 1;
    if (closed(task)) steps[index].done += 1;
  }
  return steps;
}

/** Kolumna „Skąd”: klient i forma po nazwie, reszta słowem. */
export function taskSourceLabel(task: LifecycleTask): string {
  const source = task.source ?? (task.from_template ? "path" : "manual");
  if ((source === "client" || source === "form") && task.source_label) return task.source_label;
  return TASK_SOURCE_LABELS[source];
}

// `not_yet` ma zdanie z datą (niżej) — mapa działa też, gdy typ API już go zna.
const MISSING: Record<Exclude<EntryReason, "not_yet">, string> = {
  past_start:
    "Start kontraktu już minął, więc lista wejścia nie powstała sama. Możesz ją założyć teraz.",
  no_start: "Kontrakt nie ma daty startu — lista wejścia powstanie, gdy data się pojawi.",
  closed: "Kontrakt jest zakończony albo unieważniony — wejścia nie będzie.",
  no_path:
    "Nie ma aktywnej ścieżki „Konsultant u klienta” ani pakietu klienta. Ścieżkę włącza head back office w Ustawieniach → Kadry.",
  module_off: "Moduł „Wejście i odejście” nie jest jeszcze włączony.",
};

export function missingReasonText(reason: EntryReason | null, autoCreateOn?: string | null): string {
  if (reason === "not_yet") {
    return autoCreateOn
      ? `Lista zadań powstanie sama 14 dni przed startem — ${formatIsoDatePl(autoCreateOn)}. Możesz założyć ją wcześniej.`
      : "Lista zadań powstanie sama przy najbliższym przeglądzie startów. Możesz założyć ją już teraz.";
  }
  return reason ? MISSING[reason] : "";
}

/** Przycisk zakładania: przed startem „Załóż teraz”, po starcie lista „na zaległe”. */
export function createLabel(reason: EntryReason | null): string {
  return reason === "not_yet" ? "Załóż teraz" : "Załóż listę wejścia";
}
