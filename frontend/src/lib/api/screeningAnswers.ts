// Odpowiedzi z rozmów screeningowych w profilu kandydata (02.10.2026).
//
// Arkusz Championa zapisuje się przy wierszu etapu rekrutacji, więc do tej
// zmiany nie było go widać w profilu. Serwer oddaje jedną rozmowę na
// rekrutację (najnowszy wypełniony arkusz pary), najnowsze pierwsze, w zakresie
// rekrutacji widocznych dla patrzącego — stąd `viewerScope` w kluczu.

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

export interface ScreeningConversationAnswer {
  question_id: string;
  /** `null` = pytanie usunięte z profilu Championa, zanim odpowiedzi niosły własny tekst. */
  question_text: string | null;
  response: string;
  deal_breaker_hit: boolean;
  skipped: boolean;
  /** Pochodzenie odpowiedzi (0421): `phrased`, `note_import`, `reassign_suggested`, `manual`. */
  origin?: string;
  /** Hasła rekrutera, z których powstało zdanie. */
  keywords?: string | null;
}

export interface ScreeningConversationCheck {
  kind: "domains" | "certifications" | "regulations";
  name: string;
  status: "confirmed" | "not_confirmed" | "unknown";
  note: string;
}

export interface ScreeningConversation {
  stage_id: number;
  job_id: number;
  job_title: string | null;
  client_name: string | null;
  answered_at: string | null;
  answered_by_name: string | null;
  overall_fit: "fit" | "uncertain" | "miss";
  match_percent: number;
  answers: ScreeningConversationAnswer[];
  experience_checks: ScreeningConversationCheck[];
  notes: string;
  internal_note: string | null;
}

export interface CandidateScreeningAnswers {
  candidate_id: number;
  conversations: ScreeningConversation[];
}

export function useCandidateScreeningAnswers(candidateId: number, viewerScope: string | null) {
  return useQuery<CandidateScreeningAnswers>({
    queryKey: candidateQueryKeys.screeningAnswers(candidateId, viewerScope ?? "anonymous"),
    queryFn: () =>
      api.get<CandidateScreeningAnswers>(`/api/candidates/${candidateId}/screening-answers`).then((r) => r.data),
    enabled: viewerScope != null,
    staleTime: 30_000,
  });
}
