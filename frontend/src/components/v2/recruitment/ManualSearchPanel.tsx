"use client";

/**
 * „Szukaj ręcznie" rekrutacji — wyszukiwarka kandydatów z filtrami wstępnie
 * wypełnionymi z rekrutacji i zbiorczym dodawaniem trafień do pipeline'u.
 *
 * Wyniesione 1:1 z lokalnego `ManualSearchTab` w `app/jobs/[id]/page.tsx`
 * (widok „jedna tabela", 09.2026): dawna zakładka staje się oknem wysuwanym,
 * a komponent lokalny dla strony nie dał się zaimportować. Zachowanie jest
 * identyczne — przypięte zapisane wyszukiwania, zatwierdzone wyszukiwania
 * z Profilu Championa i zbiorcze dodawanie żyją w `CandidateSearchView`,
 * którego ten panel tylko zasila. Osoby będące już w rekrutacji wycina serwer
 * (`exclude_in_job_id`).
 */

import { useQuery } from "@tanstack/react-query";

import { CandidateSearchView } from "@/components/v2/pages/CandidateSearchView";
import { buildJobSearchPrefill } from "@/lib/job-search-prefill";
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
  // używa przegląd całej bazy. `CandidateSearchView` czyta `initial` tylko przy
  // montowaniu (inicjalizator `useState`), więc montujemy go dopiero PO
  // odpowiedzi, a `key` przemontowuje formularz, gdy wymagania się zmienią.
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
  const initial = buildJobSearchPrefill(job, mustLabels);

  return (
    <CandidateSearchView
      // Klucz z TREŚCI wymagań, nie z `dataUpdatedAt`: odświeżenie przy powrocie
      // do karty z identycznymi danymi nie może kasować wpisanych filtrów.
      key={mustLabels ? `must:${mustLabels.join("|")}` : "must:fallback"}
      initial={initial}
      addToJob={{ id: jobId, title: job.title }}
      onBulkAdded={onBulkAdded}
      readOnly={readOnly}
    />
  );
}
