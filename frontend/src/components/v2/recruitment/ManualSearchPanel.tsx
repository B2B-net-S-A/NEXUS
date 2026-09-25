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
import { buildJobSearchPrefill } from "@/lib/job-search-prefill";
import { cleanRows } from "@/lib/keyword-requirements";
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

  if (
    (!savedReqs.isSuccess && !savedReqs.isError) ||
    (!champion.isSuccess && !champion.isError)
  ) {
    return <p className="p-6 text-sm text-muted-foreground">Ładowanie…</p>;
  }

  // Błąd odczytu wymagań nie blokuje wyszukiwania — prefill wraca wtedy do
  // kolumny `must_skills` rekrutacji.
  const mustLabels = savedReqs.isSuccess
    ? requirementLabels(savedReqs.data, "must")
    : null;
  // Błąd odczytu profilu nie blokuje wyszukiwania — zostaje profil z rekrutacji.
  const source = champion.isSuccess
    ? { ...job, champion_profile: champion.data?.champion_profile }
    : job;
  const search = championSearchRequirements(source);
  const hasRows = search.rows.length > 0;

  return (
    <CandidatesListV2
      // Klucz z TREŚCI wymagań, nie z `dataUpdatedAt`: odświeżenie przy powrocie
      // do karty z identycznymi danymi nie może kasować wpisanych filtrów.
      // …i z wymagań do wyszukiwania: DL zmienił wiersze = nowe filtry startowe.
      key={`${mustLabels ? `must:${mustLabels.join("|")}` : "must:fallback"}#${JSON.stringify(search)}`}
      embed={{
        jobId,
        jobTitle: job.title,
        initialFilters: jobListFilters(source, mustLabels),
        readOnly,
        onAdded: onBulkAdded,
        keywordsNote: hasRows
          ? "Wymagania ustawione przy tworzeniu rekrutacji. Zmiany tutaj nie zmieniają rekrutacji."
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
 * Filtry startowe listy z rekrutacji. Tytuł szuka po znaczeniu — tak jak
 * dotychczasowy tryb hybrydowy; w trybie „auto" dwa słowa z wielkiej litery
 * („Analityk Systemowy") wyglądałyby na nazwisko i szłyby dosłownie.
 * Status bez czarnej listy (serwer i tak by ją odrzucił przy dodaniu).
 *
 * Z wymaganiami do wyszukiwania (sekcja 2 Championa, decyzja Artura
 * 25.09.2026) start to wiersze i wykluczenia DL-a, a tytuł NIE idzie jako
 * tekst po znaczeniu: pula semantyczna zawęża wyniki i wycinałaby osoby,
 * które spełniają wymagania. Must-have zostają w rankingu jak dotąd.
 */
export function jobListFilters(
  job: ManualSearchJob,
  mustLabels: readonly string[] | null,
): CandidateFilters {
  const filters = searchRequestToListFilters(buildJobSearchPrefill(job, mustLabels));
  const { rows, exclude } = championSearchRequirements(job);
  if (rows.length > 0) {
    return {
      ...filters,
      q: "",
      textMode: "auto",
      qAll: [],
      qAny: rows,
      qNone: exclude,
      status: ["active", "passive"],
    };
  }
  return {
    ...filters,
    textMode: filters.q ? "semantic" : filters.textMode,
    status: ["active", "passive"],
  };
}
