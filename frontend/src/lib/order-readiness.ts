/**
 * Okno „Zlecenie” — lista braków bramki „Przekaż do searchu” jako wiersze
 * z działaniem.
 *
 * Reguły NIE MA tutaj: braki przychodzą z serwera (`GET /api/jobs/{id}/
 * readiness` → `blockers`, ta sama lista co przy przycisku handoffu i w doku
 * gotowości). Ten moduł tylko rozpoznaje zdanie serwera (lustro
 * `job_readiness.MSG_*` w `__fixtures__/job-readiness-blockers.json`, pilnowane
 * testem backendu) i mówi, CO z nim zrobić. Zdanie nierozpoznane (np. konflikt
 * pól Championa) zostaje brakiem z linkiem do Profilu Championa — nigdy nie
 * znika.
 */

import fixture from "@/lib/__fixtures__/job-readiness-blockers.json";

export type ReadinessKey =
  | "title"
  | "client"
  | "context"
  | "questions"
  | "must"
  | "budget"
  | "work_mode"
  | "office_days"
  | "office_city";

export const READINESS_MESSAGES: Record<ReadinessKey, string> = fixture.blockers;

const KEY_BY_MESSAGE = new Map<string, ReadinessKey>(
  (Object.entries(READINESS_MESSAGES) as Array<[ReadinessKey, string]>).map(([k, m]) => [m, k]),
);

/** Kolejność pozycji checklisty = kolejność bramki (brief, potem rubryki). */
const BASE_KEYS: readonly ReadinessKey[] = [
  "title",
  "client",
  "context",
  "questions",
  "must",
  "budget",
  "work_mode",
];
const OFFICE_KEYS: readonly ReadinessKey[] = ["office_days", "office_city"];

export const READINESS_LABEL: Record<ReadinessKey, string> = {
  title: "Rola",
  client: "Klient",
  context: "Kontekst projektu",
  questions: "2 pytania screeningowe",
  must: "Must-have",
  budget: "Budżet PLN/h",
  work_mode: "Tryb pracy",
  office_days: "Dni w biurze",
  office_city: "Miasto biura",
};

/** Kotwica sekcji Profilu Championa (`champion-section-state.ts`). */
export const READINESS_CHAMPION_ANCHOR: Record<ReadinessKey, string | null> = {
  title: null,
  client: null,
  context: "champion-section-project",
  questions: "champion-section-screening",
  must: "champion-section-stack",
  budget: "champion-section-basics",
  work_mode: "champion-section-basics",
  office_days: "champion-section-basics",
  office_city: "champion-section-basics",
};

/** Co da się zrobić z brakiem na miejscu. */
export type ReadinessAction = "budget_input" | "work_mode_buttons" | "edit_job" | "champion";

export const READINESS_ACTION: Record<ReadinessKey, ReadinessAction> = {
  title: "edit_job",
  client: "edit_job",
  context: "champion",
  questions: "champion",
  must: "champion",
  budget: "budget_input",
  work_mode: "work_mode_buttons",
  office_days: "champion",
  office_city: "champion",
};

export interface ReadinessMissing {
  /** `null` = zdanie spoza lustra — brak z linkiem do Championa. */
  key: ReadinessKey | null;
  label: string;
  message: string;
}

export interface ReadinessChecklist {
  missing: ReadinessMissing[];
  done: ReadinessKey[];
  total: number;
  doneCount: number;
}

export function readinessKeyFor(message: string): ReadinessKey | null {
  return KEY_BY_MESSAGE.get(message.trim()) ?? null;
}

/**
 * Checklista „X z Y gotowe”. Dni i miasto biura liczą się tylko przy trybie
 * hybrydowym/stacjonarnym — dokładnie wtedy, gdy bramka o nie pyta.
 */
export function buildReadinessChecklist(
  blockers: readonly string[],
  remotePolicy: string | null | undefined,
): ReadinessChecklist {
  const missing: ReadinessMissing[] = blockers.map((message) => {
    const key = readinessKeyFor(message);
    return { key, label: key ? READINESS_LABEL[key] : message, message };
  });
  const missingKeys = new Set(missing.map((m) => m.key).filter((k): k is ReadinessKey => k != null));
  const officeApplies =
    remotePolicy === "hybrid" ||
    remotePolicy === "onsite" ||
    OFFICE_KEYS.some((k) => missingKeys.has(k));
  const applicable = officeApplies ? [...BASE_KEYS, ...OFFICE_KEYS] : [...BASE_KEYS];
  const done = applicable.filter((k) => !missingKeys.has(k));
  const unknown = missing.filter((m) => m.key == null).length;
  const total = applicable.length + unknown;
  return { missing, done, total, doneCount: done.length };
}

/** Tryb pracy zapisywany w Championie (`basics.work_mode`, słownik `mode()`). */
export const WORK_MODE_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "zdalnie", label: "Zdalnie" },
  { value: "hybrydowo", label: "Hybrydowo" },
  { value: "stacjonarnie", label: "W biurze" },
];

/** Sufit budżetu — lustro `_MAX_RATE_BUDGET_HOURLY` (0, 2000] w `champion_job_sync`. */
export const MAX_BUDGET_HOURLY = 2000;

/** Liczba z pola budżetu albo komunikat, czemu nie. */
export function parseBudgetInput(raw: string): { value: number } | { error: string } {
  const text = raw.trim().replace(/\s/g, "").replace(",", ".");
  if (!text) return { error: "Wpisz kwotę w PLN/h." };
  if (!/^\d+(\.\d+)?$/.test(text)) return { error: "Wpisz samą liczbę, np. 150." };
  const value = Number(text);
  if (!(value > 0) || value > MAX_BUDGET_HOURLY) {
    return { error: `Budżet musi być większy od 0 i nie większy niż ${MAX_BUDGET_HOURLY} PLN/h.` };
  }
  return { value };
}
