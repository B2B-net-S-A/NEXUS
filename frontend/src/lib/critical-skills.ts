/**
 * Umiejętności krytyczne (0–2) — decyzja Artura 30.09.2026.
 *
 * Bramka MUST ukrywa kandydata wyłącznie za brak umiejętności krytycznej;
 * pozostałe MUST i NICE dają punkty. Stan w profilu Championa
 * (`stack.critical`):
 *  - `null`/brak klucza — Delivery Lead jeszcze nie zdecydował, działa
 *    podpowiedź z historii (≥90% wysłanych klientowi miało tę technologię),
 *  - `[]` — świadomie „Brak krytycznych”: MUST nie ukrywa nikogo,
 *  - `["Java"]` — najwyżej dwie pozycje wybrane z listy MUST, tylko
 *    technologie ze słownika (serwer odrzuca resztę 422).
 *
 * Reguły dopuszczalności i podpowiedź liczy SERWER
 * (`POST /api/job-intake/critical-suggestion`); ten moduł tylko je czyta
 * i składa zdania dla ekranu. Zapytanie i hook: `lib/critical-skills-api.ts`
 * (ten moduł jest czysty — importują go payloady i testy bez axios).
 */

export const CRITICAL_MAX = 2;

/** `null` = nie zdecydowano, `[]` = „Brak krytycznych”. */
export type CriticalValue = string[] | null;

export interface CriticalStat {
  /** Udział (0..1) wysłanych klientowi w podobnych rekrutacjach, którzy to mieli. */
  rate: number;
  /** Z ilu podobnych rekrutacji policzono udział. */
  jobs: number;
}

export interface CriticalSuggestion {
  suggested: string[];
  /** Pozycje MUST, które wolno oznaczyć jako krytyczne (technologie ze słownika). */
  eligible: string[];
  stats: Record<string, CriticalStat>;
}

/** `critical_resolution` w odpowiedzi `GET/PUT …/champion-profile`. */
export interface CriticalResolution {
  stored: string[] | null;
  decided: boolean;
  effective: string[];
  source: "dl" | "suggested" | "none";
  suggested: string[];
}

const fold = (value: string) => value.trim().toLocaleLowerCase("pl");

/** Lista MUST tak, jak ją czyta serwer: bez pustych i bez powtórek. */
export function normalizeMust(must: readonly string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of must) {
    const label = (raw ?? "").trim();
    if (!label || seen.has(fold(label))) continue;
    seen.add(fold(label));
    out.push(label);
  }
  return out;
}

export function includesLabel(list: readonly string[], label: string): boolean {
  const key = fold(label);
  return list.some((item) => fold(item) === key);
}

/**
 * Kliknięcie pozycji: zaznaczona — zdejmij (ostatnia zdjęta wraca do
 * „nie zdecydowano”, bo „Brak krytycznych” to osobny, świadomy wybór),
 * niezaznaczona — dodaj, jeśli jest miejsce.
 */
export function toggleCritical(value: CriticalValue, label: string): CriticalValue {
  const current = value ?? [];
  if (includesLabel(current, label)) {
    const next = current.filter((item) => fold(item) !== fold(label));
    return next.length > 0 ? next : null;
  }
  if (current.length >= CRITICAL_MAX) return value;
  return [...current, label];
}

/**
 * Krytyczna, której nie ma już na liście MUST, znika. Gdy znikną wszystkie
 * wybrane, wracamy do „nie zdecydowano” — pusta lista znaczyłaby „Brak
 * krytycznych”, a tego nikt nie wybrał.
 */
export function pruneCritical(value: CriticalValue, must: readonly string[]): CriticalValue {
  if (value == null || value.length === 0) return value;
  const next: string[] = [];
  for (const item of value) {
    const hit = must.find((m) => fold(m) === fold(item));
    if (hit && !includesLabel(next, hit)) next.push(hit);
  }
  if (next.length === 0) return null;
  const unchanged = next.length === value.length && next.every((item, i) => item === value[i]);
  return unchanged ? value : next;
}

/** „96% wysłanych ją miało” — tylko przy znanej statystyce. */
export function statSentence(stat: CriticalStat | undefined): string | null {
  if (!stat || !Number.isFinite(stat.rate)) return null;
  return `${Math.round(stat.rate * 100)}% wysłanych ją miało`;
}

/** Tekst przycisku podpowiedzi: „Użyj podpowiedzi: Java, Angular (z historii)”. */
export function suggestionButtonLabel(suggested: readonly string[]): string {
  return `Użyj podpowiedzi: ${suggested.join(", ")} (z historii)`;
}

/** Zdanie o tym, co dziś robi bramka MUST przy tym wyborze. */
export function criticalStatusLine(
  value: CriticalValue,
  suggested: readonly string[] | null | undefined,
): string {
  if (value == null) {
    if (suggested && suggested.length > 0) {
      return `Nie zdecydowano — działa podpowiedź: ${suggested.join(", ")}`;
    }
    return "Nie zdecydowano — brak podpowiedzi, bramka MUST nie ukrywa nikogo";
  }
  if (value.length === 0) {
    return "Brak krytycznych — bramka MUST nie ukrywa nikogo, wszystkie MUST dają punkty";
  }
  return `Krytyczne: ${value.join(", ")}`;
}

/** Linia w Podglądzie Championa. */
export function criticalBriefLine(resolution: CriticalResolution | null | undefined): string | null {
  if (!resolution) return null;
  if (resolution.decided) {
    const stored = resolution.stored ?? [];
    return stored.length > 0 ? `Krytyczne: ${stored.join(", ")}` : "Brak krytycznych";
  }
  return resolution.suggested.length > 0
    ? `Nie zdecydowano (podpowiedź: ${resolution.suggested.join(", ")})`
    : "Nie zdecydowano (brak podpowiedzi)";
}

/** Stan podpowiedzi dla pola — `useCriticalSuggestion` albo dane harnessu. */
export interface CriticalSuggestionState {
  /** Odpowiedź dla BIEŻĄCEJ listy MUST; `undefined`, dopóki jej nie ma. */
  data: CriticalSuggestion | undefined;
  /** `eligible` dla bieżącej listy; `null` = jeszcze nie wiadomo. */
  eligible: string[] | null;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  retry: () => void;
  /** Lista MUST jest pusta — nie ma z czego wybierać. */
  emptyMust: boolean;
}
