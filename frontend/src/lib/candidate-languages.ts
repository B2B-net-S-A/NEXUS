/**
 * Filtr języków na liście kandydatów (`GET /api/candidates?languages=en:B2`).
 *
 * Lista niesie wartości `kod` albo `kod:POZIOM` (poziomy CEFR + `native`),
 * powtarzany parametr. Wyszukiwarka i zapisy v3 trzymają ten sam warunek
 * jako `{code, min_level}` z kodem wielkimi literami — konwersja w obie
 * strony jest tutaj, żeby nie powstały dwie kopie reguły.
 */

export const LANGUAGE_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2", "native"] as const;
export type LanguageLevelValue = (typeof LANGUAGE_LEVELS)[number];

/**
 * Jedna lista języków: filtr listy kandydatów i okno „Języki kandydata”.
 * Kod ISO 639-1 (małe litery, jak w API), polska nazwa. Lustro backendu:
 * `candidate_language_writer._LANGUAGE_CODES` (test parytetu
 * `test_candidate_language_options_mirror.py`) — kod spoza tej listy serwer
 * przyjmuje tylko jako „Inny…” (`other: true`).
 */
export const LANGUAGE_OPTIONS: ReadonlyArray<{ code: string; label: string }> = [
  { code: "en", label: "angielski" },
  { code: "de", label: "niemiecki" },
  { code: "fr", label: "francuski" },
  { code: "es", label: "hiszpański" },
  { code: "it", label: "włoski" },
  { code: "nl", label: "niderlandzki" },
  { code: "sv", label: "szwedzki" },
  { code: "no", label: "norweski" },
  { code: "da", label: "duński" },
  { code: "fi", label: "fiński" },
  { code: "cs", label: "czeski" },
  { code: "sk", label: "słowacki" },
  { code: "uk", label: "ukraiński" },
  { code: "ru", label: "rosyjski" },
  { code: "pt", label: "portugalski" },
  { code: "pl", label: "polski" },
  { code: "hu", label: "węgierski" },
  { code: "ro", label: "rumuński" },
  { code: "bg", label: "bułgarski" },
  { code: "hr", label: "chorwacki" },
  { code: "sr", label: "serbski" },
  { code: "sl", label: "słoweński" },
  { code: "lt", label: "litewski" },
  { code: "lv", label: "łotewski" },
  { code: "et", label: "estoński" },
  { code: "el", label: "grecki" },
  { code: "tr", label: "turecki" },
  { code: "ar", label: "arabski" },
  { code: "he", label: "hebrajski" },
  { code: "zh", label: "chiński" },
  { code: "ja", label: "japoński" },
  { code: "ko", label: "koreański" },
  { code: "hi", label: "hindi" },
];

const LABEL_BY_CODE = new Map(LANGUAGE_OPTIONS.map((o) => [o.code, o.label]));
const LEVELS = new Set<string>(LANGUAGE_LEVELS);
const CODE_RE = /^[a-z]{2,3}$/;

export interface LanguageFilterEntry {
  code: string;
  level: LanguageLevelValue | null;
}

/** `en:B2` / `en` → wpis; nieczytelne wartości (ręcznie zredagowany adres) = `null`. */
export function parseLanguageFilter(raw: string): LanguageFilterEntry | null {
  const [codeRaw, levelRaw, ...rest] = raw.trim().split(":");
  if (rest.length) return null;
  const code = (codeRaw ?? "").trim().toLowerCase();
  if (!CODE_RE.test(code)) return null;
  if (levelRaw === undefined || levelRaw.trim() === "") return { code, level: null };
  const levelTrim = levelRaw.trim();
  const level = levelTrim.toLowerCase() === "native" ? "native" : levelTrim.toUpperCase();
  return LEVELS.has(level) ? { code, level: level as LanguageLevelValue } : null;
}

export function formatLanguageFilter(entry: LanguageFilterEntry): string {
  return entry.level ? `${entry.code}:${entry.level}` : entry.code;
}

/** Odczyt listy z adresu: tylko poprawne wpisy, bez duplikatów kodu. */
export function normalizeLanguageFilters(values: readonly string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of values) {
    const entry = parseLanguageFilter(value);
    if (!entry || seen.has(entry.code)) continue;
    seen.add(entry.code);
    out.push(formatLanguageFilter(entry));
  }
  return out;
}

export function languageLabel(code: string): string {
  return LABEL_BY_CODE.get(code.toLowerCase()) ?? code.toUpperCase();
}

export function levelLabel(level: LanguageLevelValue | null): string {
  if (!level) return "dowolny poziom";
  return level === "native" ? "ojczysty" : `min. ${level}`;
}

/** „angielski min. B2" — etykieta chipu aktywnego filtra. */
export function describeLanguageFilter(raw: string): string {
  const entry = parseLanguageFilter(raw);
  if (!entry) return raw;
  return entry.level
    ? `${languageLabel(entry.code)} ${levelLabel(entry.level)}`
    : languageLabel(entry.code);
}

/** Kształt wyszukiwarki / zapisu v3: `{code: "EN", min_level: "B2"}`. */
export interface UnifiedLanguageRequirement {
  code: string;
  min_level?: string;
}

export function languageFilterToUnified(raw: string): UnifiedLanguageRequirement | null {
  const entry = parseLanguageFilter(raw);
  if (!entry) return null;
  return entry.level
    ? { code: entry.code.toUpperCase(), min_level: entry.level }
    : { code: entry.code.toUpperCase() };
}

export function unifiedLanguageToFilter(value: unknown): string | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const v = value as Record<string, unknown>;
  const code = typeof v.code === "string" ? v.code : "";
  const level = typeof v.min_level === "string" ? v.min_level : "";
  const entry = parseLanguageFilter(level ? `${code}:${level}` : code);
  return entry ? formatLanguageFilter(entry) : null;
}

/** Nazwa bez wielkości liter i polskich znaków — do wyszukiwania i porównań. */
export function foldLanguageName(value: string): string {
  return value
    .toLocaleLowerCase("pl")
    .replace(/ł/g, "l")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .replace(/\s+/g, " ");
}

export function isListedLanguageCode(code: string): boolean {
  return LABEL_BY_CODE.has(code.trim().toLowerCase());
}

/** Pozycje listy pasujące do wpisanego tekstu (nazwa albo kod). */
export function searchLanguageOptions(query: string): Array<{ code: string; label: string }> {
  const folded = foldLanguageName(query);
  if (!folded) return [...LANGUAGE_OPTIONS];
  return LANGUAGE_OPTIONS.filter(
    (option) => foldLanguageName(option.label).includes(folded) || option.code === folded,
  );
}

/**
 * Kod języka spoza listy („Inny…”) — wyprowadzony z nazwy tak jak dotąd:
 * małe litery bez polskich znaków, łączniki, najwyżej 16 znaków.
 */
export function otherLanguageCode(name: string): string {
  return foldLanguageName(name)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 16);
}
