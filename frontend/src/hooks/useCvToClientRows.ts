import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import { cvToClientRowsQueryKey, type StageGeneratedCvRow } from "@/lib/cv-to-client";

/**
 * Wygenerowane CV pary (osoba × rekrutacja) — karta „CV do klienta” i ramka
 * „CV firmowe powstało z poprzedniego CV” w panelu osoby. Jeden klucz, więc
 * nowa generacja i podpięcie odświeżają oba miejsca naraz.
 */
export function useCvToClientRows(
  candidateId: number,
  jobId: number,
  options: { enabled?: boolean; refetchInterval?: number | false } = {},
) {
  return useQuery<StageGeneratedCvRow[]>({
    queryKey: cvToClientRowsQueryKey(candidateId, jobId),
    queryFn: () =>
      api
        .get<StageGeneratedCvRow[]>("/api/cv-generator/generated", {
          params: { candidate_id: candidateId, job_id: jobId, limit: 20 },
        })
        .then((r) => r.data),
    enabled: options.enabled ?? true,
    refetchInterval: options.refetchInterval ?? false,
  });
}
