// Karty rekomendacji jednej osoby w profilu kandydata (03.10.2026).
//
// Serwer oddaje najświeższe ustalenie każdego pola z kart (z datą, źródłem
// i rekrutacją), odpowiedzi na pytania zapisane w notatkach oraz to, co
// z której notatki trafiło do karty. Zakres = rekrutacje widoczne dla
// patrzącego, stąd `viewerScope` w kluczu.

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

export interface CandidateCardFact {
  key: string;
  label: string;
  raw: string;
  value: number | string | null;
  level: string | null;
  at: string | null;
  source: "note" | "manual";
  author_name: string | null;
  job_id: number | null;
  job_title: string | null;
}

export interface CandidateCardAnswer {
  number: number;
  question: string;
  answer: string;
}

export interface CandidateCardConversation {
  job_id: number;
  job_title: string | null;
  client_name: string | null;
  answered_at: string | null;
  author_name: string | null;
  note_id: number | null;
  from_traffit: boolean;
  question_count: number;
  answers: CandidateCardAnswer[];
}

export interface CandidateCardNoteLink {
  note_id: number;
  job_id: number;
  job_title: string | null;
  fields: string[];
  field_labels: string[];
  answers: number;
}

export interface CandidateCardOverview {
  candidate_id: number;
  facts: CandidateCardFact[];
  conversations: CandidateCardConversation[];
  note_links: CandidateCardNoteLink[];
}

export function useCandidateCardOverview(candidateId: number, viewerScope: string | null) {
  return useQuery<CandidateCardOverview>({
    queryKey: candidateQueryKeys.cardOverview(candidateId, viewerScope ?? "anonymous"),
    queryFn: () =>
      api
        .get<CandidateCardOverview>(`/api/candidates/${candidateId}/recommendation-cards`)
        .then((r) => r.data),
    enabled: viewerScope != null && candidateId > 0,
    staleTime: 30_000,
    // Dodatek do profilu: awaria nie może mnożyć żądań ani zasłaniać faktów.
    retry: false,
  });
}
