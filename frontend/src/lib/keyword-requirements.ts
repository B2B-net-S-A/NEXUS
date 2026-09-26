/**
 * Słowa kluczowe jako lista wymagań (decyzja Artura 25.09.2026).
 *
 * Wiersz = jedno wymaganie, słowa w wierszu = warianty („lub”), wiersze
 * łączy „i”, osobno „Wyklucz”. Na drucie każdy wiersz — także jednowyrazowy —
 * to grupa `q_any` / `q_any_group`: grupa z jednym słowem znaczy to samo co
 * dawne „Zawiera wszystkie”, a kolejność wierszy przeżywa odświeżenie. Stare
 * `q_all` (zakładki, zapisane wyszukiwania) czytamy jako wiersze na początku.
 *
 * Czyste funkcje — komponent `RequirementRowsField` i ekran Championa tylko
 * je wołają.
 */

/** Najwięcej wierszy w edytorze (serwer przyjmuje 20 — zapas na stare adresy). */
export const MAX_REQUIREMENT_ROWS = 10;

/** `|` rozdziela słowa grupy w adresie — w samym słowie zamieniamy go na spację. */
export function sanitizeKeyword(word: string): string {
  return word.replace(/\|/g, " ").replace(/\s+/g, " ").trim();
}

/**
 * Wiersze wymagań ze starych kubełków: każde słowo z „wszystkich” to osobny
 * wiersz (na początku), potem grupy „którekolwiek” w ich kolejności.
 * Puste wiersze zostają — w stanie roboczym to świeżo dodany wiersz.
 */
export function requirementRows(
  all: readonly string[],
  any: readonly (readonly string[])[],
): string[][] {
  return [...all.map((word) => [word]), ...any.map((group) => [...group])];
}

/** Wiersze do zapytania i adresu: bez pustych słów i pustych wierszy. */
export function cleanRows(rows: readonly (readonly string[])[]): string[][] {
  return rows
    .map((row) => row.map(sanitizeKeyword).filter(Boolean))
    .filter((row) => row.length > 0);
}

function rowPhrase(row: readonly string[]): string {
  return row.length > 1 ? `(${row.join(" lub ")})` : row[0];
}

/**
 * Zdanie pod polami: jak serwer przeczyta wyszukiwanie. `scopeLabel` to
 * etykieta „Szukaj w” pisana małą literą („cały profil”); `null` = bez niej
 * (edytor Championa nie ma zakresu).
 */
export function describeKeywordSearch({
  rows,
  exclude,
  scopeLabel,
}: {
  rows: readonly (readonly string[])[];
  exclude: readonly string[];
  scopeLabel: string | null;
}): string {
  const clean = cleanRows(rows);
  const without = exclude.map(sanitizeKeyword).filter(Boolean);
  if (clean.length === 0 && without.length === 0) {
    return "Brak słów kluczowych — o wynikach decydują pozostałe filtry.";
  }
  let sentence = clean.length
    ? `Szukamy osób, które mają ${clean.map(rowPhrase).join(" i ")}`
    : "Szukamy osób";
  if (without.length) sentence += `, bez słów: ${without.join(", ")}`;
  sentence += ".";
  if (scopeLabel) sentence += ` Szukamy w: ${scopeLabel}.`;
  return sentence;
}

/** Krótki opis wierszy (menu „Ostatnie wyszukiwania”, chipy). */
export function requirementLabel(row: readonly string[]): string {
  return row.join(" lub ");
}

// ── Podpowiedzi przy typowych pomyłkach ────────────────────────────────────

export interface ExperienceRange {
  min: number | null;
  max: number | null;
}

/** Słowa o stażu, które lepiej wyrazić filtrem lat doświadczenia. */
const SENIORITY: ReadonlyArray<{ words: readonly string[]; range: ExperienceRange }> = [
  { words: ["stazysta", "stazystka", "intern", "praktykant"], range: { min: null, max: 1 } },
  { words: ["junior"], range: { min: null, max: 2 } },
  { words: ["mid", "regular"], range: { min: 2, max: 5 } },
  { words: ["senior"], range: { min: 5, max: null } },
];

export function foldWord(word: string): string {
  return word
    .toLowerCase()
    .replace(/ł/g, "l")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .trim();
}

export function experienceRangeLabel(range: ExperienceRange): string {
  if (range.min === null && range.max !== null) {
    return range.max === 1 ? "do 1 roku" : `do ${range.max} lat`;
  }
  if (range.min !== null && range.max === null) return `${range.min}+ lat`;
  return `${range.min}–${range.max} lat`;
}

/** Staż, jeśli słowo go opisuje („senior” → 5+ lat); inaczej `null`. */
export function seniorityRange(word: string): ExperienceRange | null {
  const key = foldWord(word);
  return SENIORITY.find((entry) => entry.words.includes(key))?.range ?? null;
}

/**
 * Warianty wpisane w jednym słowie („React / Vue”, „React lub Vue”,
 * „React or Vue”). Ukośnik tylko ze spacjami — „CI/CD” i „PL/SQL” to jedno słowo.
 */
export function splitAlternatives(word: string): string[] | null {
  const parts = word
    .split(/\s+(?:\/|lub|or)\s+/i)
    .map(sanitizeKeyword)
    .filter((part) => part.length >= 2);
  return parts.length >= 2 ? parts : null;
}

/**
 * Krótkie słowa, które w CV znaczą najczęściej coś innego niż technologia
 * (produkcja 26.09.2026): „r” łapie „2016 r.” z klauzuli RODO w 20 845 CV,
 * „go” — „go-live”, „net” — „EURO NET”, „ada” — adresy LinkedIna. `instead`
 * to lepsze słowo tylko tam, gdzie ono istnieje; bez niego podpowiedź tylko
 * ostrzega.
 */
const AMBIGUOUS: Readonly<Record<string, { catches: string; instead?: string }>> = {
  r: { catches: "„2016 r.” z klauzuli RODO", instead: "język R" },
  go: { catches: "„go-live”", instead: "golang" },
  it: { catches: "każde „IT” w opisie firmy" },
  net: { catches: "nazwy firm, np. „EURO NET”" },
  ada: { catches: "adresy profili LinkedIn" },
  c: { catches: "pojedyncze „C” w tekście, np. „C1”, „kat. C”" },
  ai: { catches: "skrót w nazwach firm i produktów" },
  pm: { catches: "godziny, np. „5 PM”" },
  ba: { catches: "skróty w nazwach i adresach" },
  ml: { catches: "mililitry i skróty", instead: "machine learning" },
};

/** Wieloznaczne krótkie słowo (cały chip, bez wielkości liter) albo `null`. */
export function ambiguousWord(word: string): { catches: string; instead?: string } | null {
  return AMBIGUOUS[foldWord(word)] ?? null;
}

export type KeywordHint =
  | { kind: "split"; row: number; word: string; parts: string[] }
  | { kind: "seniority"; row: number; word: string; range: ExperienceRange }
  | { kind: "city"; row: number; word: string; city: string }
  | { kind: "ambiguous"; row: number; word: string; catches: string; instead?: string };

/** Podpowiedzi liczone bez serwera (warianty w jednym słowie, staż, słowa wieloznaczne). */
export function keywordHints(rows: readonly (readonly string[])[]): KeywordHint[] {
  const hints: KeywordHint[] = [];
  rows.forEach((row, index) => {
    for (const word of row) {
      const parts = splitAlternatives(word);
      if (parts) {
        hints.push({ kind: "split", row: index, word, parts });
        continue;
      }
      const range = seniorityRange(word);
      if (range) {
        hints.push({ kind: "seniority", row: index, word, range });
        continue;
      }
      const ambiguous = ambiguousWord(word);
      if (ambiguous) hints.push({ kind: "ambiguous", row: index, word, ...ambiguous });
    }
  });
  return hints;
}

/** Klucz podpowiedzi (do „Zostaw” — raz odrzucona nie wraca). */
export function hintKey(hint: Pick<KeywordHint, "kind" | "word">): string {
  return `${hint.kind}:${foldWord(hint.word)}`;
}

/** Wiersze bez jednego słowa (pusty wiersz znika). */
export function withoutWord(
  rows: readonly (readonly string[])[],
  rowIndex: number,
  word: string,
): string[][] {
  return rows
    .map((row, index) => (index === rowIndex ? row.filter((w) => w !== word) : [...row]))
    .filter((row, index) => index !== rowIndex || row.length > 0);
}

/** Wiersze, w których jedno słowo rozbito na warianty. */
export function splitWordInRow(
  rows: readonly (readonly string[])[],
  rowIndex: number,
  word: string,
  parts: readonly string[],
): string[][] {
  return rows.map((row, index) => {
    if (index !== rowIndex) return [...row];
    const out: string[] = [];
    const seen = new Set<string>();
    for (const w of row) {
      for (const piece of w === word ? parts : [w]) {
        const key = foldWord(piece);
        if (!seen.has(key)) {
          seen.add(key);
          out.push(piece);
        }
      }
    }
    return out;
  });
}

/** Dołącza słowa do wiersza (bez duplikatów, wielkość liter nie ma znaczenia). */
export function addToRow(
  rows: readonly (readonly string[])[],
  rowIndex: number,
  words: readonly string[],
): string[][] {
  return rows.map((row, index) => {
    if (index !== rowIndex) return [...row];
    const seen = new Set(row.map(foldWord));
    const out = [...row];
    for (const raw of words) {
      const word = sanitizeKeyword(raw);
      if (word.length < 2 || seen.has(foldWord(word))) continue;
      seen.add(foldWord(word));
      out.push(word);
    }
    return out;
  });
}
