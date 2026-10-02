/**
 * Filtry „Szukaj w bazie” rekrutacji — czyste funkcje, bez Reacta.
 *
 * Wyniesione z `ManualSearchPanel` i `CandidatesListV2` (02.10.2026), bo
 * te same filtry startowe liczy teraz także okno „Kandydaci do dodania”
 * i kafel z liczbą osób, a ciężkiej listy nie warto przez to ładować.
 */

import { searchRequestToListFilters } from "@/lib/candidates-search-redirect";
import { buildJobSearchPrefill, parseJobLocationCities } from "@/lib/job-search-prefill";
import { cleanRows } from "@/lib/keyword-requirements";
import { splitRequirementRows } from "@/lib/requirement-row-kinds";
import { rowHead } from "@/lib/requirement-rows";
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

/**
 * Rekrutacja prowadzona wierszami wymagań (`stack.rows`, 02.10.2026): które
 * wiersze wyszukiwania są krytyczne. `null` = profil na starych polach —
 * wtedy o obowiązkowości wiersza decyduje to, czy jest technologią.
 */
export function championCriticalRowFlags(
  job: Pick<ManualSearchJob, "champion_profile">,
  rows: readonly (readonly string[])[],
): boolean[] | null {
  const profile = job.champion_profile;
  const stack =
    profile && typeof profile === "object"
      ? (profile as { stack?: { rows?: unknown; critical?: unknown } }).stack
      : undefined;
  if (!Array.isArray(stack?.rows) || stack.rows.length === 0) return null;
  const critical = (Array.isArray(stack.critical) ? stack.critical : [])
    .filter((label): label is string => typeof label === "string")
    // Etykieta „Kafka lub RabbitMQ” wskazuje wiersz zaczynający się od „Kafka”.
    .map((label) => label.split(" lub ")[0].trim().toLocaleLowerCase("pl"));
  return rows.map((row) => critical.includes(rowHead(row).toLocaleLowerCase("pl")));
}

/**
 * Filtry startowe listy z rekrutacji. Status bez czarnej listy (serwer i tak
 * by ją odrzucił przy dodaniu).
 *
 * Miasto i kategoria rekrutacji tylko podnoszą w kolejności, nigdy nie tną
 * (audyt 26.09.2026: jako filtry wycinały 55,6% osób, które zespół potem
 * zweryfikował albo wysłał klientowi — samo miasto 58%). Wiersze wymagań:
 * obowiązkowe zostają wiersze technologii (`techRows[i] !== false`), reszta
 * („bankowość”, „narzędzia case”) tylko podnosi — wszystkie wiersze naraz
 * spełniało 39% wybranych.
 *
 * Bez wymagań w Championie (decyzja Artura 25.09.2026): cała baza spoza
 * rekrutacji ułożona według dopasowania do rekrutacji (`sort=match`, ten sam
 * wektor co kolumna „Dop.”). Dawniej tytuł szedł jako tekst po znaczeniu,
 * co ucinało listę do 200 osób; test na 120 rekrutacjach: właściwa osoba na
 * pierwszej stronie w 80% rekrutacji przy całej bazie według dopasowania.
 *
 * Z wymaganiami do wyszukiwania (sekcja 2 Championa, decyzja Artura
 * 25.09.2026) start to wiersze i wykluczenia DL-a, a tytuł NIE idzie jako
 * tekst po znaczeniu: pula semantyczna zawęża wyniki i wycinałaby osoby,
 * które spełniają wymagania. Must-have zostają w rankingu jak dotąd.
 *
 * Rekrutacja prowadzona wierszami (02.10.2026): obowiązkowe są wyłącznie
 * wiersze KRYTYCZNE, pozostałe „musi mieć” tylko podnoszą. Sześć–dziesięć
 * wierszy łączonych przez „i” zostawiało garstkę osób (audyt 26.09: wszystkie
 * wiersze naraz spełniało 39% wybranych), a krytyczne to te same słowa,
 * którymi propozycje AI ukrywają kandydatów.
 */
export function jobListFilters(
  job: ManualSearchJob,
  mustLabels: readonly string[] | null,
  techRows: ReadonlyArray<boolean | null> | null = null,
): CandidateFilters {
  const prefill = searchRequestToListFilters(buildJobSearchPrefill(job, mustLabels));
  const filters: CandidateFilters = {
    ...prefill,
    location: "",
    locationRadiusKm: null,
    competenceCategoryIds: [],
    locationPreferred:
      job.remote_policy === "remote" ? [] : parseJobLocationCities(job.location),
    competenceCategoryPreferred: job.competence_category_id ? [job.competence_category_id] : [],
  };
  const { rows, exclude } = championSearchRequirements(job);
  if (rows.length > 0) {
    const criticalFlags = championCriticalRowFlags(job, rows);
    const { required, preferred } = splitRequirementRows(rows, criticalFlags ?? techRows);
    return {
      ...filters,
      q: "",
      textMode: "auto",
      qAll: [],
      qAny: required,
      qPreferred: preferred,
      qNone: exclude,
      status: ["active", "passive"],
    };
  }
  return {
    ...filters,
    q: "",
    textMode: "auto",
    status: ["active", "passive"],
  };
}

/** Filtry zapytania listy; w trybie osadzonym z ukryciem osób z rekrutacji. */
export function candidatesListFiltersForQuery(
  filters: CandidateFilters,
  embed: { jobId: number } | null | undefined,
): CandidateFilters {
  if (!embed) return filters;
  return { ...filters, recruitmentIds: [embed.jobId], recruitmentMatch: "not_assigned" };
}
