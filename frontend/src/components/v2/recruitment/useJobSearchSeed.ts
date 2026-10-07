/**
 * Filtry startowe „Szukaj w bazie” dla rekrutacji: wiersze wymagań z sekcji 2
 * Championa (wpisuje je Delivery Lead), podzielone na obowiązkowe
 * (umiejętności krytyczne z serwera) i „mile widziane”. Te same dwa odczyty
 * i te same klucze zapytań co okno „Szukaj ręcznie” (`ManualSearchPanel`),
 * więc kafel nad Tablicą, zakładka okna i pełna wyszukiwarka startują
 * z identycznych filtrów i mówią to samo (audyt 06.10.2026, W1).
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { championApi } from "@/lib/api";
import {
  candidatesListFiltersForQuery,
  jobListFilters,
  jobSearchPlan,
  mandatorySourceNote,
  type MandatorySource,
  type ManualSearchJob,
} from "@/lib/job-search-filters";
import { matchingRequirementsApi, requirementLabels } from "@/lib/matching-requirements";
import type { CandidateFilters } from "@/lib/url-filters";

export interface JobSearchSeed {
  /** Oba odczyty się rozstrzygnęły (sukces albo błąd). */
  ready: boolean;
  /** Jest czego szukać: wiersze Championa, krytyczne z serwera albo „mile widziane”. */
  hasRows: boolean;
  required: string[][];
  preferred: string[][];
  exclude: string[];
  /** Skąd są obowiązkowe wiersze (DL, podpowiedź z historii, brak). */
  source: MandatorySource;
  /** Zdanie dla ekranu — to samo w „Szukaj ręcznie”. */
  sourceNote: string;
  /** Filtry zapytania listy (bez osób już w rekrutacji); `null` przed `ready`. */
  filters: CandidateFilters | null;
}

export function useJobSearchSeed(
  jobId: number,
  job: ManualSearchJob | null | undefined,
  enabled: boolean,
): JobSearchSeed {
  const on = enabled && job != null;
  const savedReqs = useQuery({
    queryKey: ["matching-requirements", jobId],
    queryFn: () => matchingRequirementsApi.get(jobId),
    enabled: on,
    staleTime: 60_000,
  });
  const champion = useQuery({
    queryKey: ["champion-profile", jobId],
    queryFn: () => championApi.get(jobId).then((r) => r.data),
    enabled: on,
  });
  const championSettled = champion.isSuccess || champion.isError;
  // Błąd odczytu profilu nie blokuje wyszukiwania — zostaje profil z rekrutacji.
  const source = useMemo(
    () =>
      job == null
        ? null
        : champion.isSuccess
          ? { ...job, champion_profile: champion.data?.champion_profile }
          : job,
    [job, champion.isSuccess, champion.data],
  );
  const critical = champion.isSuccess ? (champion.data?.critical_resolution ?? null) : null;
  const reqsSettled = savedReqs.isSuccess || savedReqs.isError;
  const ready = on && reqsSettled && championSettled;
  const mustLabels = useMemo(
    () => (savedReqs.isSuccess ? requirementLabels(savedReqs.data, "must") : null),
    [savedReqs.isSuccess, savedReqs.data],
  );

  return useMemo(() => {
    // Ta sama reguła „są wiersze do szukania” co okno „Szukaj ręcznie”
    // (`jobSearchPlan`): profil bez wymagań, ale z krytyczną z serwera, też
    // szuka (przegląd PR #2056).
    const plan = jobSearchPlan(source ?? {}, critical);
    const { split } = plan;
    return {
      ready,
      hasRows: plan.hasRows,
      required: split.required,
      preferred: split.preferred,
      exclude: plan.exclude,
      source: split.source,
      sourceNote: mandatorySourceNote(split),
      filters:
        ready && source
          ? candidatesListFiltersForQuery(jobListFilters(source, mustLabels, critical), { jobId })
          : null,
    };
  }, [ready, source, critical, mustLabels, jobId]);
}
