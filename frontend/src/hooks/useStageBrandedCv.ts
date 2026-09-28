import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { candidateStageCvApi, type CVBrandedState } from "@/lib/api";
import { pairSourceStageId, stageBrandedQueryKey } from "@/lib/cv-to-client";

export interface StageBrandedCv<Id extends number | null> {
  ownQuery: UseQueryResult<CVBrandedState>;
  /** Stan CV do pokazania — z wiersza pary, gdy bieżący jest pusty. */
  query: UseQueryResult<CVBrandedState>;
  pairStageId: number | null;
  /** Wiersz etapu, na którym leży CV (edycja, pobranie, link). */
  cvStageId: Id;
}

/**
 * CV do klienta osoby na etapie — z bieżącego wiersza etapu, a gdy ten jest
 * pusty, z wiersza pary wskazanego przez serwer (`pair_source_stage_id`).
 *
 * Jedna reguła dla karty „CV do klienta”, warsztatu wysyłki i profilu
 * kandydata (runda 11 i 12): odczyt, pobranie, edycja, podgląd i link dla
 * klienta idą na `cvStageId`, inaczej po ruchu na kolejną kolumnę ekran
 * twierdził „brak CV” i proponował generację od nowa.
 */
export function useStageBrandedCv(stageId: number): StageBrandedCv<number>;
export function useStageBrandedCv(stageId: number | null): StageBrandedCv<number | null>;
export function useStageBrandedCv(stageId: number | null): StageBrandedCv<number | null> {
  const ownQuery = useQuery<CVBrandedState>({
    queryKey: stageBrandedQueryKey(stageId),
    queryFn: () => candidateStageCvApi.branded.get(stageId as number).then((r) => r.data),
    enabled: stageId != null,
  });
  const pairStageId = pairSourceStageId(ownQuery.data);
  const pairQuery = useQuery<CVBrandedState>({
    queryKey: stageBrandedQueryKey(pairStageId),
    queryFn: () => candidateStageCvApi.branded.get(pairStageId as number).then((r) => r.data),
    enabled: pairStageId != null,
  });
  return {
    ownQuery,
    query: pairStageId != null ? pairQuery : ownQuery,
    pairStageId,
    cvStageId: pairStageId ?? stageId,
  };
}
