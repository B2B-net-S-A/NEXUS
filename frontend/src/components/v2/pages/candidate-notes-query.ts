"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import { candidateQueryKeys } from "./candidate-query-keys";

/* eslint-disable @typescript-eslint/no-explicit-any -- notatki z luźno typowanego endpointu */

export interface CandidateNotesResponse {
  items?: any[];
  total?: number;
  group_counts?: Record<string, number>;
}

/**
 * Wszystkie notatki osoby (`GET /api/notes?candidate_id=`) — ten sam klucz,
 * adres i surowa odpowiedź co „Historia” profilu i licznik jej zakładki, więc
 * panel osoby w rekrutacji i profil dzielą jedno pobranie. Bez `select`:
 * trzech czytników pod jednym kluczem musi widzieć tę samą treść.
 */
export function useCandidateNotes(candidateId: number, enabled = true) {
  return useQuery<CandidateNotesResponse>({
    queryKey: candidateQueryKeys.notes(candidateId),
    queryFn: ({ signal }) =>
      api.get(`/api/notes?candidate_id=${candidateId}`, { signal }).then((r) => r.data),
    enabled: enabled && candidateId > 0,
    staleTime: 30_000,
  });
}

/** `items` z odpowiedzi; atrapa albo starszy serwer bez pola daje pustą listę. */
export function candidateNoteItems(data: CandidateNotesResponse | undefined): any[] {
  return Array.isArray(data?.items) ? data.items : [];
}
