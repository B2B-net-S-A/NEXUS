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

import type { ExperienceItem } from "@/lib/api";
import { addTalkItem } from "@/lib/champion-experience";
import {
  CRITICAL_MAX,
  CRITICAL_SUGGESTION_MAX,
  type CriticalStat,
} from "@/lib/critical-skills";
import { ALTERNATIVE_SPLIT, sanitizeKeyword } from "@/lib/keyword-requirements";

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
export const CRITICAL_ROWS_MAX = CRITICAL_MAX;
/** Najwięcej słów (wariantów) w wierszu — `SEARCH_REQUIREMENT_MAX_WORDS` na serwerze. */
export const ROW_WORDS_MAX = 20;

export const LEVEL_LABEL: Record<RequirementLevel, string> = {
  critical: "Krytyczne",
  must: "Musi mieć",
  nice: "Mile widziane",
};

/**
 * Słowo, które wolno wpisać w wiersz wymagań: co najmniej 2 znaki albo jedna
 * litera („C”, „R” — technologie ze słownika). Czy to technologia, rozstrzyga
 * serwer (audyt 06.10.2026, P4). Lista kandydatów zostaje przy 2 znakach.
 */
export function acceptRequirementWord(word: string): boolean {
  const trimmed = word.trim();
  return trimmed.length >= 2 || /^\p{L}$/u.test(trimmed);
}

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

/**
 * Miejsca „mile widzianych” zajęte przez te wiersze: same „mile widziane”
 * i nadmiar obowiązkowych ponad 10 — serwer (`split_rows`) zapisuje go jako
 * „mile widziane”, dopóki jest tam miejsce (audyt 06.10.2026, N3).
 */
function niceSlotsUsed(rows: readonly RequirementRowForm[]): number {
  const required = rows.filter(isRequired).length;
  return (
    rows.filter((row) => row.level === "nice").length +
    Math.max(0, required - REQUIRED_ROWS_MAX)
  );
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
    // Liczymy też wiersze jeszcze bez słów: „Krytyczne” da się zaznaczyć przed
    // wpisaniem słowa, a taki wiersz po wypełnieniu byłby czwartym.
    const marked = rows.filter((row) => row.key !== key && row.level === "critical");
    if (marked.length >= CRITICAL_ROWS_MAX)
      return `Najwyżej ${CRITICAL_ROWS_MAX} krytyczne — zdejmij jedno, żeby dodać kolejne.`;
    // Wiersz ponad dziesiąty obowiązkowy serwer zapisuje jako „mile widziane”,
    // więc krytyczny musi się zmieścić w pierwszych dziesięciu.
    if (current.level === "nice" && others.filter(isRequired).length >= REQUIRED_ROWS_MAX)
      return `Najwyżej ${REQUIRED_ROWS_MAX} wierszy obowiązkowych — krytyczne musi się w nich zmieścić.`;
    return null;
  }
  if (level === "nice") {
    // Obowiązkowy ponad limitem już zajmuje miejsce „mile widzianego”.
    const alreadyOverflow =
      isRequired(current) && others.filter(isRequired).length >= REQUIRED_ROWS_MAX;
    if (!alreadyOverflow && niceSlotsUsed(others) >= NICE_ROWS_MAX)
      return `Najwyżej ${NICE_ROWS_MAX} wierszy „mile widziane”.`;
    return null;
  }
  // „Musi mieć” ponad 10 nie jest blokowane — serwer zapisze go jako „mile
  // widziane”, a edytor mówi to zdaniem (`requiredOverflowNotice`).
  return null;
}

/** Zdanie pod listą, gdy obowiązkowych jest więcej niż serwer zapisze jako „musi mieć”. */
export function requiredOverflowNotice(rows: readonly RequirementRowForm[]): string | null {
  return requiredRows(rows).length > REQUIRED_ROWS_MAX
    ? `Ponad ${REQUIRED_ROWS_MAX} wymagań „musi mieć” — kolejne zapiszą się jako „mile widziane”.`
    : null;
}

/** Słowo, które ma więcej osób w bazie, nic nie zawęża (audyt 06.10.2026, N8). */
export const BROAD_WORD_PEOPLE = 15_000;

/**
 * Podpowiedź przy liczbie osób w bazie dla wiersza — tylko podpowiedź, nic
 * nie blokuje. `undefined` (liczę…) i `null` (nie policzono) to nie zero.
 */
export function rowCountHint(count: number | null | undefined): string | null {
  if (count == null) return null;
  if (count === 0) return "Nikt w bazie nie ma tego słowa — sprawdź pisownię.";
  if (count > BROAD_WORD_PEOPLE) return "Słowo bardzo ogólne — zawęź (np. dodaj technologię).";
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

/** Poziom nowego wiersza: obowiązkowy, a przy pełnym limicie — „mile widziane”. */
function nextRowLevel(rows: readonly RequirementRowForm[]): RequirementLevel {
  return requiredRows(rows).length >= REQUIRED_ROWS_MAX ? "nice" : "must";
}

/** Nowy pusty wiersz: obowiązkowy, a przy pełnym limicie — „mile widziane”. */
export function addRow(rows: readonly RequirementRowForm[]): RequirementRowForm[] {
  return [...rows, { key: newRowKey(), words: [], level: nextRowLevel(rows) }];
}

/** Miejsce na kolejny wiersz: 10 obowiązkowych + 20 „mile widzianych” (z nadmiarem). */
export function canAddRow(rows: readonly RequirementRowForm[]): boolean {
  return filledRows(rows).length < REQUIRED_ROWS_MAX + NICE_ROWS_MAX;
}

// ── Wpis z klawiatury albo ze schowka (decyzja D1, 10.10.2026) ─────────────
//
// Przecinek, średnik, Enter i wklejona lista dają OSOBNE wymagania. Do 10.10
// przecinek dopisywał wariant: „Java, Spring” było jednym wierszem „Java lub
// Spring”, który spełnia kandydat z samą Javą — lista must-have po cichu się
// rozluźniała. Wariant powstaje tylko świadomie: „A / B”, „A lub B”, „A or B”
// albo przycisk „+ lub” w wypełnionym wierszu.

/** Tekst wpisany albo wklejony w pusty wiersz, rozłożony na wymagania. */
export interface RequirementEntry {
  /** Grupa = jedno wymaganie; słowa grupy to warianty („lub”). */
  groups: string[][];
  /** Słowa, których nie da się dodać (za krótkie). */
  rejected: string[];
}

/** Przecinek, średnik i nowa linia kończą wymaganie. */
const ENTRY_SEPARATOR = /[,;\r\n]+/;

/** Znacznik listy na początku wklejonej linii: „- ”, „• ”, „* ”, „1. ”, „2) ”. */
const LIST_MARKER = /^\s*(?:[-–—•·*]|\d{1,2}[.)])\s+/;

/**
 * Dzieli tekst separatorem, ale nie w domkniętym nawiasie: „Spring (Boot,
 * Data)” to jedno wymaganie. Nawias bez pary niczego nie chroni — inaczej
 * jedna literówka skleiłaby resztę wklejonej listy w jeden wiersz.
 */
function splitOutsideParens(text: string, separator: RegExp): string[] {
  const inside = new Array<boolean>(text.length).fill(false);
  const open: number[] = [];
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === "(") open.push(i);
    else if (text[i] === ")") {
      const from = open.pop();
      if (from !== undefined) inside.fill(true, from, i + 1);
    }
  }
  const every = new RegExp(separator.source, `${separator.flags.replace("g", "")}g`);
  const parts: string[] = [];
  let start = 0;
  for (const match of text.matchAll(every)) {
    if (inside[match.index]) continue;
    parts.push(text.slice(start, match.index));
    start = match.index + match[0].length;
  }
  parts.push(text.slice(start));
  return parts;
}

/**
 * Wpisany albo wklejony tekst → wymagania. Każdy kawałek między przecinkami,
 * średnikami i nowymi liniami to osobne wymaganie; „A / B”, „A lub B”,
 * „A or B” w kawałku to jego warianty („CI/CD” zostaje jednym słowem).
 */
export function parseRequirementEntry(
  text: string,
  // Lista kandydatów nie przyjmuje pojedynczej litery (`keywordLongEnough`).
  accept: (word: string) => boolean = acceptRequirementWord,
): RequirementEntry {
  const groups: string[][] = [];
  const rejected: string[] = [];
  for (const piece of splitOutsideParens(text, ENTRY_SEPARATOR)) {
    const words: string[] = [];
    for (const raw of splitOutsideParens(piece.replace(LIST_MARKER, ""), ALTERNATIVE_SPLIT)) {
      const word = sanitizeKeyword(raw);
      if (!word) continue;
      if (!accept(word)) rejected.push(word);
      else if (!words.some((w) => fold(w) === fold(word))) words.push(word);
    }
    if (words.length > 0) groups.push(words.slice(0, ROW_WORDS_MAX));
  }
  return { groups, rejected };
}

/**
 * Pole „+ lub”: wszystko, co w nim wpisano albo wklejono, to warianty TEGO
 * wiersza — także po przecinku, średniku, w nowych liniach i jako „A / B”.
 * Słowo, które wiersz już ma, nie wraca drugi raz.
 */
export function addRowVariants(
  words: readonly string[],
  text: string,
  accept: (word: string) => boolean = acceptRequirementWord,
): { words: string[]; rejected: string[] } {
  const entry = parseRequirementEntry(text, accept);
  const next = [...words];
  for (const word of entry.groups.flat()) {
    if (!next.some((existing) => fold(existing) === fold(word))) next.push(word);
  }
  return { words: next, rejected: entry.rejected };
}

export interface RequirementEntryResult {
  rows: RequirementRowForm[];
  /** Ile wymagań trafiło na listę; 0 = lista bez zmian. */
  added: number;
  /** Wiersz, w którym ma stanąć kursor; `null` = nie ma takiego wiersza. */
  focusKey: string | null;
  /** Pierwsze słowa grup, które już prowadzą inny wiersz. */
  duplicates: string[];
  /** Grupy („A lub B”), które nie zmieściły się w limicie wierszy. */
  overLimit: string[];
}

/**
 * Wymagania wpisane w wiersz `key`: pierwsza grupa wypełnia ten wiersz,
 * kolejne dochodzą pod nim jako nowe wiersze — całość jedną zmianą listy.
 * Nowy wiersz ma poziom jak z `addRow` (nigdy „krytyczne”); wiersz docelowy
 * zachowuje swój. Kursor idzie do pustego wiersza na końcu listy (nowego,
 * gdy jest miejsce); `trailing: false` (wyjście z pola) go nie dokłada.
 */
export function enterRequirements(
  rows: readonly RequirementRowForm[],
  key: string,
  groups: readonly (readonly string[])[],
  options: { trailing?: boolean } = {},
): RequirementEntryResult {
  const out = [...rows];
  const duplicates: string[] = [];
  const overLimit: string[] = [];
  let at = out.findIndex((row) => row.key === key);
  if (at < 0) return { rows: out, added: 0, focusKey: null, duplicates, overLimit };
  const heads = new Set(filledRows(out).map((row) => fold(rowHead(row.words))));
  let targetEmpty = cleanWords(out[at].words).length === 0;
  let added = 0;
  for (const group of groups) {
    const words = cleanWords(group).slice(0, ROW_WORDS_MAX);
    const head = rowHead(words);
    if (!head) continue;
    // Dwa wiersze o tym samym pierwszym słowie to jedno wymaganie — przy
    // zapisie drugi by zniknął (`filledRows`), więc mówimy to od razu.
    if (heads.has(fold(head))) {
      duplicates.push(head);
      continue;
    }
    if (!canAddRow(out)) {
      overLimit.push(words.join(" lub "));
      continue;
    }
    if (targetEmpty) {
      out[at] = { ...out[at], words };
      targetEmpty = false;
    } else {
      at += 1;
      out.splice(at, 0, { key: newRowKey(), words, level: nextRowLevel(out) });
    }
    heads.add(fold(head));
    added += 1;
  }
  if (added === 0) return { rows: out, added, focusKey: key, duplicates, overLimit };
  let focusKey: string | null = null;
  if (options.trailing !== false) {
    if (cleanWords(out[out.length - 1].words).length > 0 && canAddRow(out)) {
      out.push({ key: newRowKey(), words: [], level: nextRowLevel(out) });
    }
    const last = out[out.length - 1];
    if (cleanWords(last.words).length === 0) focusKey = last.key;
  }
  return { rows: out, added, focusKey, duplicates, overLimit };
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
  return `Nie zdecydowano — oznacz najwyżej ${CRITICAL_ROWS_MAX} wiersze jako krytyczne albo wybierz „Brak krytycznych”.`;
}

// ── Co serwer wie o wierszach (etykieta, słownik, podpowiedź z historii) ──

/**
 * Jak serwer czyta słowo wiersza (`requirement_phrase.read_phrase`, 13.10.2026,
 * wariant A): słowo do szukania albo rzecz do sprawdzenia w rozmowie.
 */
export interface PhraseReading {
  text: string;
  kind:
    | "technology"
    | "keyword"
    | "prose"
    | "soft"
    | "language"
    | "domain"
    | "category"
    | "role"
    | "city";
  /** Słowo do szukania po oczyszczeniu („SQL” z „SQL (bardzo dobra znajomość)”). */
  keyword: string | null;
  /** Treść nawiasu albo wstęp, gdy są komentarzem. */
  comment: string | null;
  /** Dokąd fraza idzie do rozmowy: sekcja 4 (`skills`/`domains`) albo pole „Język”. */
  talk: "skills" | "domains" | "language" | null;
  talk_text: string | null;
  suggestions: string[];
  needs_decision: boolean;
}

export interface RowCriticalInfo {
  /** Etykieta wiersza w `stack.must` („Kafka lub RabbitMQ”). */
  label: string;
  /** Odczyt każdego słowa wiersza (kolejność słów). */
  readings?: PhraseReading[];
  /**
   * Technologia ze słownika: od niej zależy wymóg decyzji o krytycznych,
   * podpowiedź z historii i tytuł dla rekrutera. Oznaczyć jako krytyczny
   * wolno KAŻDY wiersz — decyduje Delivery Lead (09.10.2026).
   */
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
  /** Od 13.10.2026: odczyt słów każdego wiersza (kolejność jak w żądaniu). */
  readings?: PhraseReading[][];
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
      readings: response.readings?.[index],
    };
  });
  return out;
}

/**
 * Czy bramka „Przekaż do searchu” wymaga decyzji o krytycznych: jest wiersz
 * obowiązkowy z technologią ze słownika, a DL nie oznaczył żadnego ani nie wybrał
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
    .slice(0, CRITICAL_SUGGESTION_MAX)
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

// ── Słowo do szukania czy rzecz do rozmowy (wariant A, 13.10.2026) ──

/** Rodzaje frazy, które nie mogą zostać słowem do szukania bez decyzji. */
const DECISION_KINDS = new Set<PhraseReading["kind"]>(["prose", "soft", "language", "domain"]);

/**
 * Słowo wiersza, które wymaga decyzji „zamień na słowa” albo „do rozmowy”
 * (zdanie, umiejętność miękka, język, branża opisana zdaniem). `null` = wiersz
 * jest w porządku albo serwer jeszcze nie odpowiedział.
 */
export function rowDecision(info: RowCriticalInfo | null | undefined): PhraseReading | null {
  return (
    info?.readings?.find((reading) => reading.needs_decision && DECISION_KINDS.has(reading.kind)) ??
    null
  );
}

/** Miasto wpisane jako wymaganie — podpowiedź, nie blokada. */
export function rowCity(info: RowCriticalInfo | null | undefined): PhraseReading | null {
  return info?.readings?.find((reading) => reading.kind === "city") ?? null;
}

/** Technologia z komentarzem („SQL (bardzo dobra znajomość)”) — da się rozdzielić. */
export function rowComment(info: RowCriticalInfo | null | undefined): PhraseReading | null {
  return (
    info?.readings?.find(
      (reading) =>
        !reading.needs_decision &&
        reading.keyword != null &&
        reading.comment != null &&
        fold(reading.keyword) !== fold(reading.text),
    ) ?? null
  );
}

/** Klucze wierszy, przy których decyzja jeszcze nie zapadła (blokują zapis). */
export function rowsNeedingDecision(
  rows: readonly RequirementRowForm[],
  info: Record<string, RowCriticalInfo> | null | undefined,
): string[] {
  if (!info) return [];
  return requiredRows(rows)
    .filter((row) => rowDecision(info[row.key]) != null)
    .map((row) => row.key);
}

/** Pozycja przenoszona do „Rekruter sprawdza w rozmowie” (albo pola „Język”). */
export interface TalkItem {
  name: string;
  kind: "skills" | "domains" | "language";
  level: "must" | "nice";
}

/** Najdłuższe słowo wiersza na serwerze (`SEARCH_WORD_MAX_CHARS`). */
const SERVER_WORD_MAX_CHARS = 100;

/**
 * Słowo tak, jak czyta je serwer: sito wiersza (`_search_words` — przycięcie
 * do 100 znaków na granicy wyrazu) i `_clean` z `read_phrase` (NFC, bez kropki
 * na końcu). Tekst odczytu (`PhraseReading.text`) jest już w tej postaci.
 */
function serverWord(word: string): string {
  let text = sanitizeKeyword(word);
  if (text.length > SERVER_WORD_MAX_CHARS) {
    const head = text.slice(0, SERVER_WORD_MAX_CHARS + 1);
    const cut = head.lastIndexOf(" ");
    text = (cut > 0 ? head.slice(0, cut) : text.slice(0, SERVER_WORD_MAX_CHARS)).trimEnd();
  }
  return text.normalize("NFC").replace(/[ .]+$/, "");
}

/** Słowo wiersza, które serwer przeczytał jako `text` (audyt 13.10.2026, pkt 19). */
const isReadAs = (word: string, text: string) =>
  fold(serverWord(word)) === fold(serverWord(text));

/**
 * Słowo `word` wiersza `key` zastąpione słowami `replacement` (pusta lista =
 * słowo wypada). Wiersz bez słów znika z listy. `word` może być tekstem
 * odczytu z serwera — „Doświadczenie w przetargach.” w wierszu to ten sam
 * wpis co odczyt „Doświadczenie w przetargach” (do 14.10.2026 „Do rozmowy”
 * nic nie zmieniało, a „Zapisz” zostawało zablokowane).
 */
export function replaceRowWord(
  rows: readonly RequirementRowForm[],
  key: string,
  word: string,
  replacement: readonly string[],
): RequirementRowForm[] {
  const out: RequirementRowForm[] = [];
  for (const row of rows) {
    if (row.key !== key) {
      out.push(row);
      continue;
    }
    const words: string[] = [];
    for (const current of row.words) {
      const next = isReadAs(current, word) ? replacement : [current];
      for (const candidate of next) {
        if (!words.some((w) => fold(w) === fold(candidate))) words.push(candidate);
      }
    }
    if (words.length > 0) out.push({ ...row, words });
  }
  return out;
}

/**
 * Tekst do „Rekruter sprawdza w rozmowie” dla zdania z wiersza `words`.
 * Serwer czyta słowo przycięte do 100 znaków — wtedy do rozmowy idzie całe
 * wpisane zdanie, a nie jego początek.
 */
export function talkTextFor(reading: PhraseReading, words: readonly string[]): string {
  const fallback = reading.talk_text ?? reading.text;
  const typed = words.find((word) => isReadAs(word, reading.text));
  if (typed == null) return fallback;
  const full = sanitizeKeyword(typed).normalize("NFC").replace(/[ .]+$/, "");
  return full.length > reading.text.length ? full : fallback;
}

// ── Słowo do szukania schowane na liście do rozmowy (27.10.2026) ──
//
// Lista „Rekruter sprawdza w rozmowie” nie bierze udziału w wyszukiwaniu.
// Pomiar 27.10.2026 (129 profili): technologia wpisana tylko tam to rzadkość,
// ale wtedy wyszukiwanie gubi prawdziwe wymaganie — 663525 ma „Alteryx
// (good/advanced)” na liście, a w wierszach „Data handling” i „Reporting”.

/**
 * Nazwa pozycji bez komentarza na końcu: „Excel — advanced” (tak zapis sam
 * pisze poziom z rozdzielonego wiersza, `talk_text`) i „Alteryx
 * (good/advanced)”. Czy to, co zostaje, jest słowem do szukania, mówi serwer.
 */
export function talkItemHead(name: string): string {
  const text = name.trim();
  const dash = text.search(/\s[—–-]\s/);
  const head = dash > 0 ? text.slice(0, dash) : text.replace(/\s*\([^()]*\)\s*$/, "");
  return head.trim() || text;
}

/** Teksty pozycji do odczytu: pełna nazwa i nazwa bez komentarza (gdy inna). */
export function talkItemTexts(items: readonly ExperienceItem[]): string[] {
  const out: string[] = [];
  for (const item of items) {
    for (const text of [item.name.trim(), talkItemHead(item.name)]) {
      if (text && !out.some((t) => fold(t) === fold(text))) out.push(text);
    }
  }
  return out;
}

export interface TalkSearchWord {
  item: ExperienceItem;
  /** Słowa nowego wiersza („SQL lub PostgreSQL” → dwa warianty). */
  words: string[];
  /** Pozycja zostaje na liście, bo niesie poziom albo komentarz. */
  keepItem: boolean;
}

const SEARCH_WORD_KINDS = new Set<PhraseReading["kind"]>(["technology", "keyword"]);
const bare = (word: string) => fold(word.replace(/\*+$/, ""));

/**
 * Słowo już jest w wierszach: samo albo każdym członem — „Python + SQL”
 * z 789160 serwer czyta jako jedno słowo, a Python i SQL to osobne wiersze.
 */
function coveredByRows(word: string, inRows: ReadonlySet<string>): boolean {
  if (inRows.has(bare(word))) return true;
  const parts = word.split(/\s*[+,&/]\s*|\s+/).filter((part) => part.length > 1);
  return parts.length > 1 && parts.every((part) => inRows.has(bare(part)));
}

/**
 * Pozycje listy do rozmowy, które serwer czyta jako technologię albo słowo
 * do szukania (`readings` po tekście z `talkItemTexts`), a żadnego ich słowa
 * nie ma w wierszach wymagań. Pozycja, której słowo już jest w wierszach
 * („GCP”, „BigQuery” w 789160), nie dostaje podpowiedzi.
 */
export function talkSearchWords(
  items: readonly ExperienceItem[],
  readings: Readonly<Record<string, PhraseReading | undefined>>,
  rows: readonly RequirementRowForm[],
): TalkSearchWord[] {
  const inRows = new Set(filledRows(rows).flatMap((row) => row.words.map(bare)));
  const out: TalkSearchWord[] = [];
  for (const item of items) {
    const name = item.name.trim();
    const head = talkItemHead(name);
    const reading = [readings[name], readings[head]].find(
      (r) => r != null && r.keyword && SEARCH_WORD_KINDS.has(r.kind),
    );
    if (!reading?.keyword) continue;
    const words = cleanWords(reading.keyword.split(" lub "));
    if (words.length === 0 || words.some((word) => coveredByRows(word, inRows))) continue;
    if (out.some((hint) => hint.words.some((word) => words.some((w) => fold(w) === fold(word)))))
      continue;
    const keepItem =
      fold(head) !== fold(name) ||
      reading.comment != null ||
      Boolean(item.note?.trim()) ||
      item.min_years != null;
    out.push({ item, words, keepItem });
  }
  return out;
}

/** Wiersz ze słowem z listy do rozmowy — poziom jak pozycja („Mile” → mile widziane). */
export function addTalkSearchRow(
  rows: readonly RequirementRowForm[],
  hint: TalkSearchWord,
): RequirementRowForm[] {
  const level: RequirementLevel = hint.item.level === "nice" ? "nice" : nextRowLevel(rows);
  return [...filledRows(rows), { key: newRowKey(), words: hint.words, level }];
}

/** Limity listy „Rekruter sprawdza w rozmowie” (`EXPERIENCE_ITEMS_MAX`, `…_MAX_CHARS`). */
const TALK_ITEMS_MAX = 20;
const TALK_ITEM_MAX_CHARS = 160;

/**
 * „Uprość do słów kluczowych”: zdania klienta (`descriptive` z
 * `POST /api/job-intake/requirement-rows`) do „Rekruter sprawdza w rozmowie”,
 * z poziomem z „mile widziane” (`nice`). Co się nie mieści — ponad 20 pozycji
 * albo zdanie dłuższe niż 160 znaków (na liście zostaje jego skrót) — idzie
 * w całości do opisu wymagań, jak w „Wymaganiach do poprawy”. Do 14.10.2026
 * zapis zostawiał 20 zdań, resztę gubił, a długie ucinał (audyt 13.10, pkt 21).
 */
export function talkFromDescriptive(
  skills: readonly ExperienceItem[],
  notes: string,
  descriptive: readonly string[],
  nice: readonly string[],
): { skills: ExperienceItem[]; notes: string } {
  let items = [...skills];
  const overflow: string[] = [];
  for (const raw of descriptive) {
    const sentence = raw.trim().replace(/\s+/g, " ");
    if (!sentence) continue;
    const level = nice.includes(raw) ? "nice" : "must";
    const name = sentence.slice(0, TALK_ITEM_MAX_CHARS).toLowerCase();
    const known = items.some((i) => i.name.toLowerCase() === name);
    if (!known && items.length >= TALK_ITEMS_MAX) {
      overflow.push(sentence);
      continue;
    }
    items = addTalkItem(items, sentence, level);
    if (sentence.length > TALK_ITEM_MAX_CHARS) overflow.push(sentence);
  }
  if (overflow.length === 0) return { skills: items, notes };
  const note = `Do sprawdzenia w rozmowie: ${overflow.join("; ")}.`;
  return { skills: items, notes: [notes.trim(), note].filter(Boolean).join("\n") };
}

/** Ile osób zostawiają krytyczne razem — poniżej tej liczby pytamy (D2). */
export const CRITICAL_PEOPLE_MIN = 20;

/** Zdanie pod listą, gdy krytyczne razem zostawiają mało osób; `null` = w porządku. */
export function criticalReachWarning(count: number | null | undefined): string | null {
  if (count == null || count >= CRITICAL_PEOPLE_MIN) return null;
  return count === 0
    ? "Krytyczne razem nie zostawiają nikogo w bazie — propozycje AI i „Szukaj w bazie” będą puste."
    : `Krytyczne razem zostawiają ${count.toLocaleString("pl-PL")} ${count === 1 ? "osobę" : count < 5 ? "osoby" : "osób"} z bazy — propozycje AI pokażą tylko je.`;
}
