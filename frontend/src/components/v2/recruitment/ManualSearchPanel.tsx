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
import type { CandidateFilters } from "@/lib/url-filters";
import {
  matchingRequirementsApi,
  requirementLabels,
} from "@/lib/matching-requirements";

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

  if (!savedReqs.isSuccess && !savedReqs.isError) {
    return <p className="p-6 text-sm text-muted-foreground">Ładowanie…</p>;
  }

  // Błąd odczytu wymagań nie blokuje wyszukiwania — prefill wraca wtedy do
  // kolumny `must_skills` rekrutacji.
  const mustLabels = savedReqs.isSuccess
    ? requirementLabels(savedReqs.data, "must")
    : null;

  return (
    <CandidatesListV2
      // Klucz z TREŚCI wymagań, nie z `dataUpdatedAt`: odświeżenie przy powrocie
      // do karty z identycznymi danymi nie może kasować wpisanych filtrów.
      key={mustLabels ? `must:${mustLabels.join("|")}` : "must:fallback"}
      embed={{
        jobId,
        jobTitle: job.title,
        initialFilters: jobListFilters(job, mustLabels),
        readOnly,
        onAdded: onBulkAdded,
      }}
    />
  );
}

/**
 * Filtry startowe listy z rekrutacji. Tytuł szuka po znaczeniu — tak jak
 * dotychczasowy tryb hybrydowy; w trybie „auto" dwa słowa z wielkiej litery
 * („Analityk Systemowy") wyglądałyby na nazwisko i szłyby dosłownie.
 * Status bez czarnej listy (serwer i tak by ją odrzucił przy dodaniu).
 */
export function jobListFilters(
  job: ManualSearchJob,
  mustLabels: readonly string[] | null,
): CandidateFilters {
  const filters = searchRequestToListFilters(buildJobSearchPrefill(job, mustLabels));
  return {
    ...filters,
    textMode: filters.q ? "semantic" : filters.textMode,
    status: ["active", "passive"],
  };
}
