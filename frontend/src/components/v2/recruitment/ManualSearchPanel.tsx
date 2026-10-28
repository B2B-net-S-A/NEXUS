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
 *
 * Dodana osoba znika z wyników, więc nad listą stoi „Dodani teraz” z „Cofnij”
 * (15 min) i „Pasuje też do” — jak w pozostałych zakładkach okna (15.10.2026).
 */

import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  CandidatesListV2,
  type CandidatesListAddedPerson,
  type CandidatesListAiRequest,
} from "@/components/v2/pages/CandidatesListV2";
import {
  championSearchRequirements,
  jobListFilters,
  jobSearchPlan,
  mandatorySourceNote,
  type ManualSearchJob,
} from "@/lib/job-search-filters";
import {
  matchingRequirementsApi,
  requirementLabels,
} from "@/lib/matching-requirements";
import { championApi } from "@/lib/api";
import { aiAssessmentApi } from "@/lib/ai-assessment";
import { countPl } from "@/lib/plural-pl";

import { ManualAddedStrip } from "./ManualAddedStrip";
import { useUndoWindow } from "./useUndoWindow";

export interface ManualSearchPanelProps {
  jobId: number;
  job: ManualSearchJob;
  onBulkAdded?: () => void;
  readOnly?: boolean;
  /** „✦ Oceń z AI” na zaznaczonych — panel oceny pokazuje okno (28.10.2026). */
  onAssessWithAi?: (request: CandidatesListAiRequest) => void;
  /** „Ostatnia ocena AI · Otwórz” — zapisana ocena bez ponownego wywołania. */
  onOpenLatestAi?: () => void;
}

export function ManualSearchPanel({
  jobId,
  job,
  onBulkAdded,
  readOnly = false,
  onAssessWithAi,
  onOpenLatestAi,
}: ManualSearchPanelProps) {
  // Dodani w tym oknie (przeżywa przemontowanie listy po zmianie wymagań).
  const [added, setAdded] = useState<readonly CandidatesListAddedPerson[]>([]);
  // Cofnięci — lista z powrotem pokazuje przy nich „Dodaj”.
  const [undone, setUndone] = useState<ReadonlySet<number>>(() => new Set());
  const undoWindow = useUndoWindow();
  const { start: startUndoWindow } = undoWindow;
  const onAdded = useCallback(
    (people: CandidatesListAddedPerson[]) => {
      const ids = new Set(people.map((p) => p.candidateId));
      // Ponowne dodanie po „Cofnij” = osoba znów na końcu (najnowsza).
      setAdded((prev) => [...prev.filter((p) => !ids.has(p.candidateId)), ...people]);
      setUndone((prev) =>
        [...ids].some((id) => prev.has(id)) ? new Set([...prev].filter((id) => !ids.has(id))) : prev,
      );
      startUndoWindow([...ids]);
      onBulkAdded?.();
    },
    [onBulkAdded, startUndoWindow],
  );
  const onUndone = useCallback((candidateId: number) => {
    setAdded((prev) => prev.filter((p) => p.candidateId !== candidateId));
    setUndone((prev) => new Set(prev).add(candidateId));
  }, []);
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
  // Ostatnia ocena AI tej osoby w rekrutacji (≤ 7 dni) — odczyt z bazy, bez modelu.
  const latestAi = useQuery({
    queryKey: ["ai-assessment-latest", jobId],
    queryFn: () => aiAssessmentApi.latest(jobId),
    enabled: Boolean(onOpenLatestAi),
  });
  const latestCount = latestAi.data?.rows.length ?? 0;

  if ((!savedReqs.isSuccess && !savedReqs.isError) || !championSettled) {
    return <p className="p-6 text-sm text-muted-foreground">Ładowanie…</p>;
  }

  // Błąd odczytu wymagań nie blokuje wyszukiwania — prefill wraca wtedy do
  // kolumny `must_skills` rekrutacji.
  const mustLabels = savedReqs.isSuccess
    ? requirementLabels(savedReqs.data, "must")
    : null;
  // Ta sama reguła „są wiersze do szukania” co zakładka „Szukaj w bazie”
  // i kafel (`jobSearchPlan`, przegląd PR #2056).
  const { split, hasRows } = jobSearchPlan(source, critical);

  return (
    <div className="space-y-3">
      {onOpenLatestAi && latestCount > 0 ? (
        <p className="text-xs text-muted-foreground" data-testid="ai-assessment-latest">
          Ostatnia ocena AI: {countPl(latestCount, "osoba", "osoby", "osób")}{" "}
          <button type="button" className="font-medium text-primary underline" onClick={onOpenLatestAi}>
            Otwórz
          </button>
        </p>
      ) : null}
      <ManualAddedStrip
        jobId={jobId}
        people={added}
        undoExpired={undoWindow.expired}
        readOnly={readOnly}
        onUndone={onUndone}
      />
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
          onAdded,
          undone,
          onAssessWithAi,
          mustRows: split.must,
          keywordsNote: hasRows
            ? `Wymagania z rekrutacji. ${mandatorySourceNote(split)} Zmiany tutaj nie zmieniają rekrutacji.`
            : undefined,
        }}
      />
    </div>
  );
}

// Filtry startowe żyją w `lib/job-search-filters.ts` (wspólne z oknem
// „Kandydaci do dodania”); eksport zostaje dla dotychczasowych importów.
export { championSearchRequirements, jobListFilters, type ManualSearchJob };
