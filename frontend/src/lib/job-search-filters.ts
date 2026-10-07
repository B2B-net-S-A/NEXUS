/**
 * Filtry „Szukaj w bazie” rekrutacji — czyste funkcje, bez Reacta.
 *
 * Wyniesione z `ManualSearchPanel` i `CandidatesListV2` (02.10.2026), bo
 * te same filtry startowe liczy teraz także okno „Kandydaci do dodania”
 * i kafel z liczbą osób, a ciężkiej listy nie warto przez to ładować.
 */

import { searchRequestToListFilters } from "@/lib/candidates-search-redirect";
import { buildJobSearchPrefill, parseJobLocationCities } from "@/lib/job-search-prefill";
import type { CriticalResolution } from "@/lib/critical-skills";
import { cleanRows, foldWord, keywordLongEnough, SINGLE_LETTER_HINT } from "@/lib/keyword-requirements";
import type { CandidateFilters } from "@/lib/url-filters";

/** Pola rekrutacji, z których powstaje prefill filtrów. */
export interface ManualSearchJob {
  id: number;
  title: string;
  description?: string | null;
  requirements?: string | null;
  seniority?: string | null;
  must_skills?: unknown;
  nice_skills?: unknown;
  competence_category_id?: number | null;
  salary_min?: number | null;
  salary_max?: number | null;
  location?: string | null;
  remote_policy?: string | null;
  /** Sekcja 2 Championa niesie wymagania do wyszukiwania (25.09.2026). */
  champion_profile?: unknown;
}

/** Wiersze i wykluczenia z sekcji 2 Championa (puste pomijane). */
export function championSearchRequirements(job: Pick<ManualSearchJob, "champion_profile">): {
  rows: string[][];
  exclude: string[];
} {
  const profile = job.champion_profile;
  const search =
    profile && typeof profile === "object"
      ? (profile as { search?: { requirements?: unknown; exclude?: unknown } }).search
      : undefined;
  const words = (value: unknown): string[] =>
    Array.isArray(value) ? value.filter((w): w is string => typeof w === "string") : [];
  const rows = cleanRows(Array.isArray(search?.requirements) ? search.requirements.map(words) : []);
  const exclude = words(search?.exclude).map((w) => w.trim()).filter(Boolean);
  return { rows, exclude };
}

/** Wiersze „mile widziane” z `stack.rows` (W6) — nie trafiają do `search.requirements`. */
export function championNiceRows(job: Pick<ManualSearchJob, "champion_profile">): string[][] {
  const profile = job.champion_profile;
  const stack =
    profile && typeof profile === "object"
      ? (profile as { stack?: { rows?: unknown } }).stack
      : undefined;
  if (!Array.isArray(stack?.rows)) return [];
  const rows: string[][] = [];
  for (const row of stack.rows) {
    if (!row || typeof row !== "object") continue;
    const { words, level } = row as { words?: unknown; level?: unknown };
    if (level !== "nice" || !Array.isArray(words)) continue;
    rows.push(words.filter((w): w is string => typeof w === "string"));
  }
  return cleanRows(rows);
}

/**
 * Wersja na końcu nazwy („Java 11+”, „Spring Boot 3.x”, „Python (3.10)”,
 * „Oracle min. 19c”) — odcinana jak w bramce AI (`strip_version`), żeby
 * krytyczna „Java 11+” trafiła w wiersz „Java”. Wymaga odstępu albo nawiasu
 * przed wersją: „ES6”, „S3” i „C++” zostają.
 */
const TRAILING_VERSION =
  /(?:\s+|\s*\()(?:v|ver\.?|wersja|wersji|min\.?|minimum|minimalna|od)?\s*\d[\w.]*\s*\+?\s*(?:or higher|i wyżej|lub wyższa|lub nowsza)?\s*\)?$/i;

export function withoutVersion(word: string): string {
  let text = word.trim();
  for (let i = 0; i < 3; i += 1) {
    const next = text.replace(TRAILING_VERSION, "").trim();
    if (next === text || !next) break;
    text = next;
  }
  return text;
}

const foldKey = (word: string) => foldWord(withoutVersion(word.replace(/\*+$/, "")));

/**
 * Opcje etykiety tak, jak czyta je bramka AI (lustro uproszczone
 * `must_gate_terms.gate_requirement`): bez wersji, „A / B”, „A lub B”,
 * „A or B” i przykłady w nawiasie („Bazy danych (Oracle, PostgreSQL)”).
 * Tylko dla odpowiedzi bez `search_rows` — serwer liczy je sam.
 */
function labelOptions(label: string): string[] {
  const text = withoutVersion(label);
  const examples = text.match(/^(.+?)\s*\(([^()]+)\)$/);
  const parts =
    examples && /[,/]|\s(?:lub|or)\s/i.test(examples[2])
      ? examples[2].split(/\s*,\s*|\s*\/\s*|\s+(?:lub|or|i|and)\s+/i)
      : /^ci\/cd$/i.test(text)
        ? [text]
        : text.split(/\s*\/\s*|\s+(?:lub|or)\s+/i);
  return parts.map((part) => withoutVersion(part)).filter(Boolean);
}

/**
 * Wiersze obowiązkowe z serwera (`critical_resolution.search_rows`): po
 * jednym na krytyczną, z wariantami nazwy. Odpowiedź sprzed 06.10.2026 nie
 * ma `search_rows` — wtedy wiersz to opcje etykiety (`labelOptions`).
 */
export function criticalSearchRows(critical: CriticalResolution | null | undefined): string[][] {
  if (!critical) return [];
  if (Array.isArray(critical.search_rows)) return cleanRows(critical.search_rows);
  return cleanRows(
    (critical.effective ?? [])
      .map(labelOptions)
      .filter((row) => row.every((word) => keywordLongEnough(word))),
  );
}

/** Skąd są obowiązkowe wiersze — ekran mówi to zdaniem. */
export type MandatorySource = "dl" | "suggested" | "none" | "unknown";

export interface MandatorySplit {
  /** Wiersze, które wycinają (krytyczne) — z wariantami. */
  required: string[][];
  /** Wiersze, które tylko podnoszą w kolejności. */
  preferred: string[][];
  source: MandatorySource;
  /** Etykiety krytycznych („Kafka lub RabbitMQ”). */
  labels: string[];
  /** Krytyczne bez wiersza słów kluczowych („C”, „R”). */
  skipped: string[];
}

/**
 * Jedna reguła obowiązkowości dla „Szukaj ręcznie”, „Szukaj w bazie” i kafla
 * (audyt 06.10.2026, D1/W1–W5): wycinają WYŁĄCZNIE umiejętności krytyczne
 * tak, jak liczy je serwer (`critical_resolution`: wybór Delivery Leada albo
 * podpowiedź z historii) — te same, którymi propozycje AI ukrywają
 * kandydatów. Wiersz Championa z tą technologią dostaje warianty nazwy
 * z serwera; krytyczna bez wiersza (profil bez `stack.rows`, W3) dochodzi jako
 * nowy wiersz. Reszta wierszy i wiersze „mile widziane” (W6) tylko podnoszą.
 * Klasyfikacja „technologia / nie” nie decyduje już o obowiązkowości.
 */
export function splitByCritical(
  rows: readonly (readonly string[])[],
  niceRows: readonly (readonly string[])[],
  critical: CriticalResolution | null | undefined,
): MandatorySplit {
  const criticalRows = criticalSearchRows(critical);
  const required: string[][] = [];
  const used = new Set<number>();
  for (const words of criticalRows) {
    const keys = new Set(words.map(foldKey));
    const index = rows.findIndex(
      (row, i) => !used.has(i) && row.some((word) => keys.has(foldKey(word))),
    );
    if (index < 0) {
      required.push([...words]);
      continue;
    }
    used.add(index);
    const merged = [...rows[index]];
    // Dopisujemy słowa serwera dosłownie (bez odcinania wersji): wiersz
    // „Java 17” sam w sobie jest węższy niż bramka AI („Java”).
    const exact = (w: string) => foldWord(w.replace(/\*+$/, ""));
    for (const word of words) {
      if (!merged.some((w) => exact(w) === exact(word))) merged.push(word);
    }
    required.push(merged);
  }
  const preferred: string[][] = rows.filter((_, i) => !used.has(i)).map((row) => [...row]);
  for (const row of niceRows) {
    const key = row.map(foldKey).join("|");
    if (!preferred.some((r) => r.map(foldKey).join("|") === key)) preferred.push([...row]);
  }
  return {
    required,
    preferred,
    source: critical ? critical.source : "unknown",
    labels: critical ? [...(critical.effective ?? [])] : [],
    skipped: critical
      ? Array.isArray(critical.search_rows)
        ? [...(critical.search_rows_skipped ?? [])]
        : (critical.effective ?? []).filter((label) =>
            labelOptions(label).some((word) => !keywordLongEnough(word)),
          )
      : [],
  };
}

/** Zdanie o obowiązkowych wierszach — „Szukaj ręcznie”, „Szukaj w bazie”, kafel. */
export function mandatorySourceNote(
  split: Pick<MandatorySplit, "source" | "labels"> & Partial<Pick<MandatorySplit, "skipped">>,
): string {
  const labels = split.labels.join(", ");
  const skipped = split.skipped ?? [];
  const skippedNote = skipped.length
    ? ` ${skipped.map((w) => `„${w}”`).join(", ")} nie jest słowem kluczowym (jedna litera znalazłaby prawie każdego) — propozycje AI i tak sprawdzają to w profilu. ${SINGLE_LETTER_HINT}`
    : "";
  if (split.source === "dl" && labels) {
    return `Obowiązkowe są tylko umiejętności krytyczne wybrane przez Delivery Leada: ${labels}. Pozostałe wymagania tylko podnoszą w kolejności.${skippedNote}`;
  }
  if (split.source === "suggested" && labels) {
    return `Obowiązkowe są tylko umiejętności krytyczne z podpowiedzi z historii (Delivery Lead ich nie wybrał): ${labels}. Pozostałe wymagania tylko podnoszą w kolejności.${skippedNote}`;
  }
  if (split.source === "unknown") {
    return "Nie udało się wczytać umiejętności krytycznych — nic nie jest obowiązkowe, wymagania tylko podnoszą w kolejności.";
  }
  return "Brak umiejętności krytycznych — nic nie jest obowiązkowe, wymagania tylko podnoszą w kolejności.";
}

/** Wymagania Championa podzielone na obowiązkowe i „mile widziane” + czy jest czego szukać. */
export interface JobSearchPlan {
  rows: string[][];
  exclude: string[];
  split: MandatorySplit;
  /**
   * Jedna reguła „są wiersze do szukania” dla okna „Szukaj ręcznie”, zakładki
   * „Szukaj w bazie” i kafla (przegląd PR #2056): wiersze Championa,
   * krytyczne z serwera albo wiersze „mile widziane”.
   */
  hasRows: boolean;
}

export function jobSearchPlan(
  job: Pick<ManualSearchJob, "champion_profile">,
  critical: CriticalResolution | null | undefined,
): JobSearchPlan {
  const { rows, exclude } = championSearchRequirements(job);
  const split = splitByCritical(rows, championNiceRows(job), critical);
  return {
    rows,
    exclude,
    split,
    hasRows: rows.length > 0 || split.required.length > 0 || split.preferred.length > 0,
  };
}

/**
 * Filtry startowe listy z rekrutacji. Status bez czarnej listy (serwer i tak
 * by ją odrzucił przy dodaniu).
 *
 * Miasto i kategoria rekrutacji tylko podnoszą w kolejności, nigdy nie tną
 * (audyt 26.09.2026: jako filtry wycinały 55,6% osób, które zespół potem
 * zweryfikował albo wysłał klientowi — samo miasto 58%).
 *
 * Bez wymagań w Championie (decyzja Artura 25.09.2026): cała baza spoza
 * rekrutacji ułożona według dopasowania do rekrutacji (`sort=match`, ten sam
 * wektor co kolumna „Dop.”). Dawniej tytuł szedł jako tekst po znaczeniu,
 * co ucinało listę do 200 osób.
 *
 * Obowiązkowe są wyłącznie umiejętności krytyczne z serwera
 * (`splitByCritical`, audyt 06.10.2026) — dla profili z wierszami i bez.
 * Przy wierszach wymagań must-have NIE idą dodatkowo do „Umiejętności → Mile
 * widziane” (D2): ta sama technologia liczyła się dwa razy, a „Mile widziane”
 * wygrywało z „Dop.” w kolejności.
 */
export function jobListFilters(
  job: ManualSearchJob,
  mustLabels: readonly string[] | null,
  critical: CriticalResolution | null = null,
): CandidateFilters {
  const prefill = searchRequestToListFilters(buildJobSearchPrefill(job, mustLabels));
  const filters: CandidateFilters = {
    ...prefill,
    q: "",
    textMode: "auto",
    status: ["active", "passive"],
    location: "",
    locationRadiusKm: null,
    competenceCategoryIds: [],
    locationPreferred:
      job.remote_policy === "remote" ? [] : parseJobLocationCities(job.location),
    competenceCategoryPreferred: job.competence_category_id ? [job.competence_category_id] : [],
  };
  const { rows, exclude, split, hasRows } = jobSearchPlan(job, critical);
  if (!hasRows) return filters;
  if (rows.length > 0) {
    return {
      ...filters,
      skillsPreferred: [],
      skillsExpr: "",
      qAll: [],
      qAny: split.required,
      qPreferred: split.preferred,
      qNone: exclude,
    };
  }
  return { ...filters, qAll: [], qAny: split.required, qPreferred: split.preferred };
}

/** Filtry zapytania listy; w trybie osadzonym z ukryciem osób z rekrutacji. */
export function candidatesListFiltersForQuery(
  filters: CandidateFilters,
  embed: { jobId: number } | null | undefined,
): CandidateFilters {
  if (!embed) return filters;
  return { ...filters, recruitmentIds: [embed.jobId], recruitmentMatch: "not_assigned" };
}
