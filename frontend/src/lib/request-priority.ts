/**
 * Priorytet rekrutacji w trzech poziomach (decyzja Artura 02.10.2026) —
 * lustro `backend/app/services/job_priority.py`.
 *
 * Kolumna `jobs.priority` ma cztery wartości (`low` / `medium` / `high` /
 * `urgent`), ekrany i filtry mówią poziomami: „P1 Pilne”, „P2 Standard”
 * i „Przyjmujemy kandydatów”. Serwer oddaje poziom w polu `priority_level`;
 * dopóki go nie ma (starszy backend, stare fixture'y), poziom liczymy tutaj
 * z surowej wartości — tą samą regułą co serwer.
 */

export type PriorityLevel = "p1" | "p2" | "accepting";

/** Wartości kolumny `jobs.priority` (`JobPriority` w backendzie). */
export type RawJobPriority = "low" | "medium" | "high" | "urgent";

/** Kolejność na ekranie: od najpilniejszego. */
export const PRIORITY_LEVELS: readonly PriorityLevel[] = ["p1", "p2", "accepting"];

export const PRIORITY_LEVEL_LABEL: Record<PriorityLevel, string> = {
  p1: "P1 Pilne",
  p2: "P2 Standard",
  accepting: "Przyjmujemy kandydatów",
};

/**
 * Poziom, od którego zaczyna nowa rekrutacja (decyzja Artura 08.10.2026,
 * do tej daty P2). Lustro `NEW_JOB_PRIORITY_LEVEL` w backendzie — tę samą
 * wartość serwer nadaje, gdy `POST /api/jobs` przychodzi bez priorytetu.
 */
export const NEW_JOB_PRIORITY_LEVEL: PriorityLevel = "p1";

/** Krótka etykieta — wiersz tabeli, plakietka. */
export const PRIORITY_LEVEL_SHORT_LABEL: Record<PriorityLevel, string> = {
  p1: "P1",
  p2: "P2",
  accepting: "Przyjmujemy",
};

/** Gotowe opcje wyboru (przełącznik priorytetu, filtr listy). */
export const PRIORITY_LEVEL_OPTIONS: ReadonlyArray<{
  value: PriorityLevel;
  label: string;
}> = PRIORITY_LEVELS.map((value) => ({
  value,
  label: PRIORITY_LEVEL_LABEL[value],
}));

/** Wartość kolumny zapisywana dla poziomu (`PATCH /api/jobs/{id} {priority}`). */
const RAW_BY_LEVEL: Record<PriorityLevel, RawJobPriority> = {
  p1: "urgent",
  p2: "medium",
  accepting: "low",
};

export function isPriorityLevel(value: unknown): value is PriorityLevel {
  return (
    typeof value === "string" &&
    (PRIORITY_LEVELS as readonly string[]).includes(value)
  );
}

/** Pola rekrutacji albo requestu, z których czytamy priorytet. */
export interface PrioritySource {
  /** Poziom policzony przez serwer (od 02.10.2026). */
  priority_level?: string | null;
  /** Surowa wartość kolumny — zapas, gdy serwer nie oddał poziomu. */
  priority?: string | null;
}

/**
 * Poziom priorytetu rekrutacji. `priority_level` z serwera wygrywa; bez niego
 * (albo z wartością, której ten front nie zna) poziom wynika z `priority`:
 * `urgent` i `high` → P1, `low` → „Przyjmujemy kandydatów”, reszta — także
 * brak i nieznana wartość — to P2, czyli stan domyślny.
 */
export function priorityLevelOf(
  job: PrioritySource | null | undefined,
): PriorityLevel {
  const level = job?.priority_level;
  if (isPriorityLevel(level)) return level;
  switch ((job?.priority ?? "").trim().toLowerCase()) {
    case "urgent":
    case "high":
      return "p1";
    case "low":
      return "accepting";
    default:
      return "p2";
  }
}

export function rawPriorityForLevel(level: PriorityLevel): RawJobPriority {
  return RAW_BY_LEVEL[level];
}
