"use client";

/**
 * „Szukaj ręcznie" rekrutacji — od 25.09.2026 ta sama lista co ekran
 * „Kandydaci" (pasek słów kluczowych, przyciski filtrów, tabela), w trybie
 * osadzonym (`CandidatesListV2 embed`). Decyzja Artura: wygląd i silnik jak
 * lista; odpadły przypięte zapisane wyszukiwania, diagnostyka pustego wyniku,
 * shortlista i opcje etapu/notatki/tagów przy dodawaniu.
 *
 * Filtry startują z rekrutacji (`buildJobSearchPrefill` → filtry listy),
 * tekst tytułu liczy się po znaczeniu (jak dotąd w trybie hybrydowym), osoby
 * już w rekrutacji ukrywa zapytanie (`recruitment_match=not_assigned`), a
 * „Dodaj" wpisuje do „Nowych" (`proposals/bulk`, źródło `manual_search`).
 */

import { useQuery } from "@tanstack/react-query";

import { CandidatesListV2 } from "@/components/v2/pages/CandidatesListV2";
import { searchRequestToListFilters } from "@/lib/candidates-search-redirect";
import { buildJobSearchPrefill, parseJobLocationCities } from "@/lib/job-search-prefill";
import { cleanRows } from "@/lib/keyword-requirements";
import { classifyRequirementRows, splitRequirementRows } from "@/lib/requirement-row-kinds";
import type { CandidateFilters } from "@/lib/url-filters";
import {
  matchingRequirementsApi,
  requirementLabels,
} from "@/lib/matching-requirements";
import { championApi } from "@/lib/api";

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

export interface ManualSearchPanelProps {
  jobId: number;
  job: ManualSearchJob;
  onBulkAdded?: () => void;
  readOnly?: boolean;
}

export function ManualSearchPanel({
  jobId,
  job,
  onBulkAdded,
  readOnly = false,
}: ManualSearchPanelProps) {
  // Wymagania obowiązkowe z zapisanego kontraktu rekrutacji — ten sam, którego
  // używa przegląd całej bazy. Lista czyta filtry startowe tylko przy
  // montowaniu, więc montujemy ją dopiero PO odpowiedzi, a `key`
  // przemontowuje ją, gdy wymagania się zmienią.
  const savedReqs = useQuery({
    queryKey: ["matching-requirements", jobId],
    queryFn: () => matchingRequirementsApi.get(jobId),
  });
  // Wymagania do wyszukiwania czytamy z profilu Championa tym samym kluczem
  // co edytor — po zapisie DL-a okno ma świeże wiersze, nie te z odczytu
  // rekrutacji sprzed edycji.
  const champion = useQuery({
    queryKey: ["champion-profile", jobId],
    queryFn: () => championApi.get(jobId).then((r) => r.data),
  });
  // Błąd odczytu profilu nie blokuje wyszukiwania — zostaje profil z rekrutacji.
  const source = champion.isSuccess
    ? { ...job, champion_profile: champion.data?.champion_profile }
    : job;
  const search = championSearchRequirements(source);
  const championSettled = champion.isSuccess || champion.isError;
  // Który wiersz wymagań to technologia (audyt 26.09.2026): obowiązkowe
  // zostają tylko wiersze technologii, reszta tylko podnosi w kolejności.
  // `null` przy błędzie = wiersz obowiązkowy, jak dotąd (bezpieczny kierunek).
  const rowKinds = useQuery({
    queryKey: ["manual-search-row-kinds", search.rows],
    queryFn: () => classifyRequirementRows(search.rows),
    enabled: championSettled && search.rows.length > 0,
    // Runda 8 (R8-N14-7): wynik klasyfikacji jest w `key` listy. Odświeżenie
    // przy powrocie do karty (np. `null` po limicie czasu → `false`)
    // przemontowałoby listę i skasowało wpisany szkic filtrów. Nowe wiersze
    // DL-a to nowy klucz zapytania, więc staleness nic tu nie wnosi.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  if (
    (!savedReqs.isSuccess && !savedReqs.isError) ||
    !championSettled ||
    (search.rows.length > 0 && !rowKinds.isSuccess && !rowKinds.isError)
  ) {
    return <p className="p-6 text-sm text-muted-foreground">Ładowanie…</p>;
  }

  // Błąd odczytu wymagań nie blokuje wyszukiwania — prefill wraca wtedy do
  // kolumny `must_skills` rekrutacji.
  const mustLabels = savedReqs.isSuccess
    ? requirementLabels(savedReqs.data, "must")
    : null;
  const hasRows = search.rows.length > 0;
  const techRows = rowKinds.isSuccess ? rowKinds.data : null;

  return (
    <CandidatesListV2
      // Klucz z TREŚCI wymagań, nie z `dataUpdatedAt`: odświeżenie przy powrocie
      // do karty z identycznymi danymi nie może kasować wpisanych filtrów.
      // …i z wymagań do wyszukiwania: DL zmienił wiersze = nowe filtry startowe.
      key={`${mustLabels ? `must:${mustLabels.join("|")}` : "must:fallback"}#${JSON.stringify(search)}#${JSON.stringify(techRows)}`}
      embed={{
        jobId,
        jobTitle: job.title,
        initialFilters: jobListFilters(source, mustLabels, techRows),
        readOnly,
        onAdded: onBulkAdded,
        keywordsNote: hasRows
          ? "Wymagania ustawione przy tworzeniu rekrutacji: technologie są obowiązkowe, pozostałe wiersze tylko podnoszą w kolejności. Zmiany tutaj nie zmieniają rekrutacji."
          : undefined,
      }}
    />
  );
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
    const { required, preferred } = splitRequirementRows(rows, techRows);
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
