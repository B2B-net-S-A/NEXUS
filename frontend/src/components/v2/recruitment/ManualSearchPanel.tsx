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
import {
  championNiceRows,
  championSearchRequirements,
  jobListFilters,
  mandatorySourceNote,
  splitByCritical,
  type ManualSearchJob,
} from "@/lib/job-search-filters";
import {
  matchingRequirementsApi,
  requirementLabels,
} from "@/lib/matching-requirements";
import { championApi } from "@/lib/api";

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
  // Wymagania do wyszukiwania i umiejętności krytyczne czytamy z profilu
  // Championa tym samym kluczem co edytor — po zapisie DL-a okno ma świeże
  // wiersze, nie te z odczytu rekrutacji sprzed edycji.
  const champion = useQuery({
    queryKey: ["champion-profile", jobId],
    queryFn: () => championApi.get(jobId).then((r) => r.data),
  });
  // Błąd odczytu profilu nie blokuje wyszukiwania — zostaje profil z rekrutacji.
  const source = champion.isSuccess
    ? { ...job, champion_profile: champion.data?.champion_profile }
    : job;
  // Krytyczne liczy serwer (wybór DL albo podpowiedź z historii) — te same,
  // którymi propozycje AI ukrywają kandydatów (audyt 06.10.2026, D1/W1–W5).
  const critical = champion.isSuccess ? (champion.data?.critical_resolution ?? null) : null;
  const search = championSearchRequirements(source);
  const championSettled = champion.isSuccess || champion.isError;

  if ((!savedReqs.isSuccess && !savedReqs.isError) || !championSettled) {
    return <p className="p-6 text-sm text-muted-foreground">Ładowanie…</p>;
  }

  // Błąd odczytu wymagań nie blokuje wyszukiwania — prefill wraca wtedy do
  // kolumny `must_skills` rekrutacji.
  const mustLabels = savedReqs.isSuccess
    ? requirementLabels(savedReqs.data, "must")
    : null;
  const split = splitByCritical(search.rows, championNiceRows(source), critical);
  const hasRows = search.rows.length > 0 || split.required.length > 0;

  return (
    <CandidatesListV2
      // Klucz z TREŚCI wymagań, nie z `dataUpdatedAt`: odświeżenie przy powrocie
      // do karty z identycznymi danymi nie może kasować wpisanych filtrów.
      // …i z wymagań do wyszukiwania oraz krytycznych: DL zmienił wiersze =
      // nowe filtry startowe.
      key={`${mustLabels ? `must:${mustLabels.join("|")}` : "must:fallback"}#${JSON.stringify(search)}#${JSON.stringify(split)}`}
      embed={{
        jobId,
        jobTitle: job.title,
        initialFilters: jobListFilters(source, mustLabels, critical),
        readOnly,
        onAdded: onBulkAdded,
        keywordsNote: hasRows
          ? `Wymagania z rekrutacji. ${mandatorySourceNote(split)} Zmiany tutaj nie zmieniają rekrutacji.`
          : undefined,
      }}
    />
  );
}

// Filtry startowe żyją w `lib/job-search-filters.ts` (wspólne z oknem
// „Kandydaci do dodania”); eksport zostaje dla dotychczasowych importów.
export { championSearchRequirements, jobListFilters, type ManualSearchJob };
