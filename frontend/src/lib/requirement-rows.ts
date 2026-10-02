/**
 * Wymagania rekrutacji jako jedna lista słów kluczowych (02.10.2026).
 *
 * Wiersz = wymaganie, słowa w wierszu = warianty (wystarczy jedno), poziom =
 * krytyczne / musi mieć / mile widziane. Do 02.10 Delivery Lead wpisywał to
 * samo trzy razy: must-have, umiejętności krytyczne i „wymagania do
 * wyszukiwania w bazie”. Zapis to `stack.rows` w Profilu Championa; pola,
 * które czyta reszta systemu (`stack.must`, `stack.nice`, `stack.critical`,
 * `search.requirements`), wyprowadza z wierszy SERWER
 * (`backend/app/services/champion_requirement_rows.py`).
 *
 * Czyste funkcje — bez Reacta i sieci. Etykiety wierszy i to, które wolno
 * oznaczyć jako krytyczne, liczy serwer (`lib/requirement-rows-api.ts`).
 */

import type { CriticalStat } from "@/lib/critical-skills";
import { sanitizeKeyword } from "@/lib/keyword-requirements";

export type RequirementLevel = "critical" | "must" | "nice";

export interface RequirementRowForm {
  /** Stały klucz Reacta — wiersz nie gubi wpisywanego tekstu przy zmianach obok. */
  key: string;
  words: string[];
  level: RequirementLevel;
}

/** Wiersz w zapisie i w odpowiedziach API. */
export interface StoredRequirementRow {
  words: string[];
  level: RequirementLevel;
}

/** Limity jak na serwerze (`clean_rows`). */
export const REQUIRED_ROWS_MAX = 10;
export const NICE_ROWS_MAX = 20;
export const CRITICAL_ROWS_MAX = 2;

export const LEVEL_LABEL: Record<RequirementLevel, string> = {
  critical: "Krytyczne",
  must: "Musi mieć",
  nice: "Mile widziane",
};

let rowSeq = 0;
export function newRowKey(): string {
  rowSeq += 1;
  return `r-${Date.now().toString(36)}-${rowSeq}`;
}

const fold = (value: string) => value.trim().toLocaleLowerCase("pl");

function cleanWords(words: readonly string[]): string[] {
  const out: string[] = [];
  for (const raw of words) {
    const word = sanitizeKeyword(raw ?? "");
    if (word && !out.some((w) => fold(w) === fold(word))) out.push(word);
  }
  return out;
}

/**
 * Słowo, po którym wiersz jest rozpoznawany: pierwsze bez gwiazdki, a gdy są
 * same rdzenie — pierwszy rdzeń bez gwiazdki (lustro `_head` na serwerze).
 */
export function rowHead(words: readonly string[]): string {
  const clean = cleanWords(words);
  for (const word of clean) if (!word.endsWith("*")) return word;
  return clean.length > 0 ? clean[0].replace(/\*+$/, "").trim() : "";
}

/**
 * Wiersze, które pójdą do zapisu: bez pustych, a dwa wiersze o tym samym
 * pierwszym słowie to jedno wymaganie (zostaje pierwszy).
 */
export function filledRows(rows: readonly RequirementRowForm[]): RequirementRowForm[] {
  const out: RequirementRowForm[] = [];
  const heads = new Set<string>();
  for (const row of rows) {
    const words = cleanWords(row.words);
    const head = fold(rowHead(words));
    if (!head || heads.has(head)) continue;
    heads.add(head);
    out.push({ ...row, words });
  }
  return out;
}

const isRequired = (row: RequirementRowForm) => row.level !== "nice";

export function requiredRows(rows: readonly RequirementRowForm[]): RequirementRowForm[] {
  return filledRows(rows).filter(isRequired);
}

export function criticalRows(rows: readonly RequirementRowForm[]): RequirementRowForm[] {
  return filledRows(rows).filter((row) => row.level === "critical");
}

/** Nazwy „musi mieć” (z krytycznymi) — pierwsze słowa wierszy. */
export function mustHeads(rows: readonly RequirementRowForm[]): string[] {
  return requiredRows(rows).map((row) => rowHead(row.words));
}

export function niceHeads(rows: readonly RequirementRowForm[]): string[] {
  return filledRows(rows)
    .filter((row) => row.level === "nice")
    .map((row) => rowHead(row.words));
}

/** Wiersze do wyszukiwania w bazie: krytyczne i „musi mieć”, ze wszystkimi słowami. */
export function searchRows(rows: readonly RequirementRowForm[]): string[][] {
  return requiredRows(rows).map((row) => [...row.words]);
}

export function countLevel(
  rows: readonly RequirementRowForm[],
  level: RequirementLevel,
): number {
  return filledRows(rows).filter((row) => row.level === level).length;
}

/** Czy wiersz może dostać ten poziom (limity z serwera); `null` = tak. */
export function levelBlockedReason(
  rows: readonly RequirementRowForm[],
  key: string,
  level: RequirementLevel,
): string | null {
  const current = rows.find((row) => row.key === key);
  if (!current || current.level === level) return null;
  const others = filledRows(rows).filter((row) => row.key !== key);
  if (level === "critical") {
    if (others.filter((row) => row.level === "critical").length >= CRITICAL_ROWS_MAX)
      return `Najwyżej ${CRITICAL_ROWS_MAX} krytyczne — zdejmij jedno, żeby dodać kolejne.`;
  }
  if (level === "nice") {
    if (others.filter((row) => row.level === "nice").length >= NICE_ROWS_MAX)
      return `Najwyżej ${NICE_ROWS_MAX} wierszy „mile widziane”.`;
    return null;
  }
  if (current.level === "nice" && others.filter(isRequired).length >= REQUIRED_ROWS_MAX)
    return `Najwyżej ${REQUIRED_ROWS_MAX} wierszy obowiązkowych.`;
  return null;
}

export function setRowLevel(
  rows: readonly RequirementRowForm[],
  key: string,
  level: RequirementLevel,
): RequirementRowForm[] {
  if (levelBlockedReason(rows, key, level)) return [...rows];
  return rows.map((row) => (row.key === key ? { ...row, level } : row));
}

/** Nowy pusty wiersz: obowiązkowy, a przy pełnym limicie — „mile widziane”. */
export function addRow(rows: readonly RequirementRowForm[]): RequirementRowForm[] {
  const level: RequirementLevel =
    requiredRows(rows).length >= REQUIRED_ROWS_MAX ? "nice" : "must";
  return [...rows, { key: newRowKey(), words: [], level }];
}

export function canAddRow(rows: readonly RequirementRowForm[]): boolean {
  const filled = filledRows(rows);
  return (
    filled.filter(isRequired).length < REQUIRED_ROWS_MAX ||
    filled.filter((row) => row.level === "nice").length < NICE_ROWS_MAX
  );
}

/** Wiersze do `stack.rows` w zapisie profilu (poziom „krytyczne” czyta serwer). */
export function toStoredRows(rows: readonly RequirementRowForm[]): StoredRequirementRow[] {
  return filledRows(rows).map((row) => ({ words: row.words, level: row.level }));
}

/**
 * `stack.critical` do zapisu, gdy żaden wiersz nie jest krytyczny: `[]` =
 * świadome „Brak krytycznych”, `null` = nie zdecydowano. Przy wierszach
 * krytycznych serwer bierze je z poziomów.
 */
export function criticalDecision(
  rows: readonly RequirementRowForm[],
  noCritical: boolean,
): string[] | null {
  return criticalRows(rows).length === 0 && noCritical ? [] : null;
}

function labelMatchesRow(label: string, words: readonly string[]): boolean {
  const first = label.split(" lub ")[0];
  return fold(first) === fold(rowHead(words)) && fold(first) !== "";
}

/**
 * Wiersze z zapisu albo z odczytu requestu. W zapisanym profilu poziom to
 * „musi mieć” / „mile widziane”, a krytyczne mówi `stack.critical` (etykiety
 * wierszy) — tu wracają jako poziom wiersza.
 */
export function rowsFromStored(
  stored: unknown,
  critical: readonly string[] | null | undefined = null,
): RequirementRowForm[] {
  if (!Array.isArray(stored)) return [];
  const rows: RequirementRowForm[] = [];
  for (const item of stored) {
    if (!item || typeof item !== "object") continue;
    const raw = item as { words?: unknown; level?: unknown };
    const words = cleanWords(
      Array.isArray(raw.words)
        ? raw.words.filter((w): w is string => typeof w === "string")
        : [],
    );
    if (words.length === 0) continue;
    const level: RequirementLevel =
      raw.level === "nice" ? "nice" : raw.level === "critical" ? "critical" : "must";
    rows.push({ key: newRowKey(), words, level });
  }
  let marked = rows.filter((row) => row.level === "critical").length;
  for (const label of critical ?? []) {
    const row = rows.find(
      (r) => r.level === "must" && labelMatchesRow(label, r.words),
    );
    if (row && marked < CRITICAL_ROWS_MAX) {
      row.level = "critical";
      marked += 1;
    }
  }
  return filledRows(rows);
}

/** Zdanie pod listą: jak krytyczne działają przy tym wyborze. */
export function criticalSummary(
  rows: readonly RequirementRowForm[],
  noCritical: boolean,
): string {
  const critical = criticalRows(rows).map((row) => rowHead(row.words));
  if (critical.length > 0)
    return `Krytyczne: ${critical.join(", ")} — propozycje AI ukrywają osoby, które ich nie mają.`;
  if (noCritical)
    return "Brak krytycznych — propozycje AI nie ukrywają nikogo, wszystkie wymagania dają punkty.";
  return "Nie zdecydowano — oznacz najwyżej dwa wiersze jako krytyczne albo wybierz „Brak krytycznych”.";
}

// ── Co serwer wie o wierszach (etykieta, czy wolno oznaczyć jako krytyczny) ──

export interface RowCriticalInfo {
  /** Etykieta wiersza w `stack.must` („Kafka lub RabbitMQ”). */
  label: string;
  /** Technologia ze słownika — wolno oznaczyć jako krytyczną. */
  eligible: boolean;
  /** Podpowiedź z historii (≥ 90% wysłanych klientowi ją miało). */
  suggested: boolean;
  stat?: CriticalStat;
}

/** Stan podpowiedzi dla edytora — hook albo dane harnessu. */
export interface RowCriticalState {
  /** Po kluczu wiersza; `null` = jeszcze nie wiadomo (nie „nic”). */
  info: Record<string, RowCriticalInfo> | null;
  isLoading: boolean;
  isError: boolean;
  retry: () => void;
}

export const EMPTY_ROW_CRITICAL_STATE: RowCriticalState = {
  info: null,
  isLoading: false,
  isError: false,
  retry: () => undefined,
};

/** Odpowiedź `POST /api/job-intake/critical-suggestion` z `rows`. */
export interface RowCriticalResponse {
  labels?: string[];
  eligible: string[];
  suggested: string[];
  stats: Record<string, CriticalStat>;
}

/** Odpowiedź serwera → informacja per wiersz (kolejność jak w żądaniu). */
export function rowCriticalInfo(
  rows: readonly RequirementRowForm[],
  response: RowCriticalResponse,
): Record<string, RowCriticalInfo> {
  const out: Record<string, RowCriticalInfo> = {};
  const has = (list: readonly string[], label: string) =>
    list.some((item) => fold(item) === fold(label));
  requiredRows(rows).forEach((row, index) => {
    const label = response.labels?.[index] || rowHead(row.words);
    out[row.key] = {
      label,
      eligible: has(response.eligible ?? [], label),
      suggested: has(response.suggested ?? [], label),
      stat: response.stats?.[label],
    };
  });
  return out;
}

/**
 * Czy bramka „Przekaż do searchu” wymaga decyzji o krytycznych: jest wiersz
 * obowiązkowy, który wolno oznaczyć, a DL nie oznaczył żadnego ani nie wybrał
 * „Brak krytycznych”. `info == null` = nie wiadomo — nie zgadujemy.
 */
export function criticalDecisionMissing(
  rows: readonly RequirementRowForm[],
  noCritical: boolean,
  info: Record<string, RowCriticalInfo> | null | undefined,
): boolean {
  if (noCritical || criticalRows(rows).length > 0 || info == null) return false;
  return requiredRows(rows).some((row) => info[row.key]?.eligible);
}

/** Wiersze podpowiedziane z historii, których DL jeszcze nie oznaczył. */
export function suggestedRowKeys(
  rows: readonly RequirementRowForm[],
  info: Record<string, RowCriticalInfo> | null | undefined,
): string[] {
  if (!info) return [];
  return requiredRows(rows)
    .filter((row) => info[row.key]?.suggested && info[row.key]?.eligible)
    .slice(0, CRITICAL_ROWS_MAX)
    .map((row) => row.key);
}

/** „Użyj podpowiedzi”: oznacza podpowiedziane wiersze, resztę krytycznych zdejmuje. */
export function applySuggestion(
  rows: readonly RequirementRowForm[],
  keys: readonly string[],
): RequirementRowForm[] {
  return rows.map((row) => {
    if (keys.includes(row.key)) return { ...row, level: "critical" as const };
    return row.level === "critical" ? { ...row, level: "must" as const } : row;
  });
}
