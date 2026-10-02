"use client";

/**
 * Filtry startowe „Szukaj w bazie” dla rekrutacji: wiersze wymagań z sekcji 2
 * Championa (wpisuje je Delivery Lead), podzielone na obowiązkowe
 * (technologie) i „mile widziane”. Te same trzy odczyty i te same klucze
 * zapytań co okno „Szukaj ręcznie” (`ManualSearchPanel`), więc kafel nad
 * Tablicą, zakładka okna i pełna wyszukiwarka startują z identycznych filtrów.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { championApi } from "@/lib/api";
import {
  candidatesListFiltersForQuery,
  championSearchRequirements,
  jobListFilters,
  type ManualSearchJob,
} from "@/lib/job-search-filters";
import { matchingRequirementsApi, requirementLabels } from "@/lib/matching-requirements";
import { classifyRequirementRows, splitRequirementRows } from "@/lib/requirement-row-kinds";
import type { CandidateFilters } from "@/lib/url-filters";

export interface JobSearchSeed {
  /** Wszystkie trzy odczyty się rozstrzygnęły (sukces albo błąd). */
  ready: boolean;
  /** Delivery Lead wpisał w Championie choć jeden wiersz wymagań. */
  hasRows: boolean;
  required: string[][];
  preferred: string[][];
  exclude: string[];
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
  const search = useMemo(
    () => (source ? championSearchRequirements(source) : { rows: [], exclude: [] }),
    [source],
  );
  const rowKinds = useQuery({
    queryKey: ["manual-search-row-kinds", search.rows],
    queryFn: () => classifyRequirementRows(search.rows),
    enabled: on && championSettled && search.rows.length > 0,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const reqsSettled = savedReqs.isSuccess || savedReqs.isError;
  const kindsSettled = search.rows.length === 0 || rowKinds.isSuccess || rowKinds.isError;
  const ready = on && reqsSettled && championSettled && kindsSettled;
  const mustLabels = useMemo(
    () => (savedReqs.isSuccess ? requirementLabels(savedReqs.data, "must") : null),
    [savedReqs.isSuccess, savedReqs.data],
  );
  const techRows = rowKinds.isSuccess ? rowKinds.data : null;

  return useMemo(() => {
    const split = splitRequirementRows(search.rows, techRows);
    return {
      ready,
      hasRows: search.rows.length > 0,
      required: split.required,
      preferred: split.preferred,
      exclude: search.exclude,
      filters:
        ready && source
          ? candidatesListFiltersForQuery(
              jobListFilters(source, mustLabels, techRows),
              { jobId },
            )
          : null,
    };
  }, [ready, source, search, techRows, mustLabels, jobId]);
}
