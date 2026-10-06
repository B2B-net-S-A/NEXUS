"use client";

/**
 * Karta rekomendacji pary (kandydat, rekrutacja) — 0413.
 *
 * Serwer składa kartę z notatek rekrutera i z pól wpisanych w NEXUSIE (te
 * zawsze wygrywają), liczy kompletność i tekst w dotychczasowym formacie
 * działu. Front niczego tu nie wylicza — pokazuje i zapisuje pojedyncze pola.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import api from "@/lib/api";
import { MOVE_REQUIREMENTS_PREFIX } from "@/lib/api/moveRequirements";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

export interface RecommendationCardField {
  raw: string;
  /** Skąd wartość: notatka rekrutera albo pole wpisane w NEXUSIE. */
  source?: "note" | "manual";
  note_id?: number | null;
  at?: string | null;
  by?: number | null;
  by_name?: string | null;
  /** Pochodzenie pola wpisanego w NEXUSIE (0421): z notatki (AI / reguła wzoru)
   *  albo zdanie ułożone z haseł. Zwykła edycja zdejmuje to pole. */
  origin?: CardFieldOrigin;
  /** Hasła, z których powstało zdanie (`phrased`). */
  keywords?: string;
  [normalized: string]: unknown;
}

export type CardFieldOrigin = "note_ai" | "note_rule" | "phrased";
export type CardAnswerOrigin = "note_import" | "phrased" | "note_sync";

export interface RecommendationCardQuestion {
  number: number;
  question: string;
  answer: string;
  /** `sheet` = arkusz screeningu, `note` = notatka, `null` = brak odpowiedzi. */
  source: "sheet" | "note" | null;
  /** Identyfikator pytania Championa (arkusz screeningu) — klucz zapisu
   *  trafienia „Odpada, gdy…”. Brak przy pytaniach tylko z notatki. */
  question_id?: string | number | null;
  /** „Odpada, gdy…” z Profilu Championa — treść odpowiedzi, która wyklucza. */
  deal_breaker?: string | null;
  /** Rekruter oznaczył, że odpowiedź narusza „Odpada, gdy…”. */
  deal_breaker_hit?: boolean;
  /** Odpowiedź z arkusza przyjęta z notatki albo ułożona z haseł (0421). */
  origin?: CardAnswerOrigin;
  keywords?: string;
}

export interface RecommendationCardCompleteness {
  status: "complete" | "partial" | "empty";
  filled: number;
  total: number;
  missing: string[];
}

export interface RecommendationCard {
  candidate_id: number;
  job_id: number;
  exists: boolean;
  fields: Record<string, RecommendationCardField>;
  /** Wartości sprzed bieżącej próby procesu — tylko podpowiedź. */
  previous: Record<string, RecommendationCardField>;
  suggestions: Record<string, string>;
  questions: RecommendationCardQuestion[];
  completeness: RecommendationCardCompleteness;
  labels: Record<string, string>;
  editable_fields: string[];
  legacy_text: string;
  updated_at?: string | null;
  /** Kafle „Wgraj notatkę” / „Wklej tekst” i „Ułóż w zdanie” (0421). */
  assist_enabled?: boolean;
  /** Język zdań = język CV klienta rekrutacji. */
  phrase_language?: PhraseLanguage | null;
}

export type PhraseLanguage = "pl" | "en";

/** Pole karty w przeglądzie propozycji z notatki. */
export interface NoteProposalField {
  key: string;
  label: string;
  current: string | null;
  current_source: "note" | "manual" | null;
  proposed: string;
  /** Dosłowny fragment notatki (odczyt AI); `null` = reguła wzoru działu. */
  quote: string | null;
  origin: "note_ai" | "note_rule";
  changed: boolean;
}

/** Odpowiedź na pytanie Championa w przeglądzie propozycji. */
export interface NoteProposalAnswer {
  question_id: string;
  number: number;
  question: string;
  current: string | null;
  /** Fragment notatki z odpowiedzią — hasła rekrutera. */
  keywords: string;
  /** Zdanie ułożone z haseł; `null` = nie ułożono albo odrzucone. */
  sentence: string | null;
  /** Fakt spoza notatki, przez który zdanie odrzucono. */
  problem: string | null;
}

export interface NoteProposal {
  fields: NoteProposalField[];
  answers: NoteProposalAnswer[];
  /** `false` = Luna nie odpowiedziała; propozycja ma tylko odczyt reguły. */
  available: boolean;
  message: string | null;
  language: PhraseLanguage;
  /** Zmiana stawki otworzy sprawę „zmiana stawki” i dzwonek do DL. */
  rate_change_notifies: boolean;
  /** Tekst notatki (z pliku albo wklejony) — idzie do zapisu jako notatka. */
  text: string;
}

export interface NoteApplyAnswer {
  question_id: string;
  response: string;
  keywords?: string | null;
  origin: CardAnswerOrigin;
}

export interface NoteApplyInput {
  text: string;
  source_name?: string | null;
  fields: Record<string, string>;
  field_origins: Record<string, "note_ai" | "note_rule">;
  answers: NoteApplyAnswer[];
}

export interface PhraseRequestItem {
  key: string;
  keywords: string;
  question?: string | null;
}

export interface PhraseResultItem {
  key: string;
  sentence: string | null;
  problem: string | null;
}

export interface PhraseResult {
  available: boolean;
  message: string | null;
  language: PhraseLanguage;
  items: PhraseResultItem[];
}

export interface CardSaveInput {
  fields: Record<string, string | null>;
  /** Pola opisowe ułożone z haseł („Ułóż w zdanie”). */
  origins?: Record<string, { origin: "phrased"; keywords: string }>;
}

/** Odczyt notatki trwa do ~1 min (model). */
const NOTE_READ_TIMEOUT_MS = 120_000;

export const recommendationCardQueryKey = (candidateId: number, jobId: number) =>
  ["recommendation-card", jobId, candidateId] as const;

export const recommendationCardsApi = {
  get: async (candidateId: number, jobId: number, signal?: AbortSignal) =>
    (
      await api.get<RecommendationCard>("/api/recommendation-cards", {
        params: { candidate_id: candidateId, job_id: jobId },
        signal,
      })
    ).data,
  save: async (candidateId: number, jobId: number, input: CardSaveInput) =>
    (
      await api.put<RecommendationCard>("/api/recommendation-cards", {
        candidate_id: candidateId,
        job_id: jobId,
        fields: input.fields,
        ...(input.origins && Object.keys(input.origins).length ? { origins: input.origins } : {}),
      })
    ).data,
  /** Propozycja karty i odpowiedzi z wklejonej notatki — bez zapisu. */
  readNote: async (candidateId: number, jobId: number, text: string) =>
    (
      await api.post<NoteProposal>(
        "/api/recommendation-cards/note/read",
        { candidate_id: candidateId, job_id: jobId, text },
        { timeout: NOTE_READ_TIMEOUT_MS },
      )
    ).data,
  /** Propozycja z wgranego pliku (.docx, .pdf, .txt) — pliku nie zapisujemy. */
  readNoteFile: async (candidateId: number, jobId: number, file: File) => {
    const body = new FormData();
    body.append("candidate_id", String(candidateId));
    body.append("job_id", String(jobId));
    body.append("file", file);
    return (
      await api.post<NoteProposal>("/api/recommendation-cards/note/read-file", body, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: NOTE_READ_TIMEOUT_MS,
      })
    ).data;
  },
  /** Zapis zaznaczonych pozycji: notatka w historii, pola karty, odpowiedzi w arkuszu. */
  applyNote: async (candidateId: number, jobId: number, input: NoteApplyInput) =>
    (
      await api.post<RecommendationCard>("/api/recommendation-cards/note/apply", {
        candidate_id: candidateId,
        job_id: jobId,
        ...input,
      })
    ).data,
  /** „Ułóż w zdanie” — bez zapisu. */
  phrase: async (
    candidateId: number,
    jobId: number,
    items: PhraseRequestItem[],
    language?: PhraseLanguage | null,
  ) =>
    (
      await api.post<PhraseResult>(
        "/api/recommendation-cards/phrase",
        { candidate_id: candidateId, job_id: jobId, items, ...(language ? { language } : {}) },
        { timeout: NOTE_READ_TIMEOUT_MS },
      )
    ).data,
  /** Trafienie „Odpada, gdy…” jednego pytania — zwraca całą kartę. */
  setDealBreakerHit: async (
    candidateId: number,
    jobId: number,
    questionId: string | number,
    hit: boolean,
  ) =>
    (
      await api.post<RecommendationCard>("/api/recommendation-cards/deal-breaker", {
        candidate_id: candidateId,
        job_id: jobId,
        question_id: questionId,
        hit,
      })
    ).data,
};

/** Po zapisie karty: plakietka na tablicy i lista „Przesuń dalej” czytają ten sam stan. */
function refreshCardDependents(
  queryClient: ReturnType<typeof useQueryClient>,
  candidateId: number,
  jobId: number,
  card: RecommendationCard,
) {
  queryClient.setQueryData(recommendationCardQueryKey(candidateId, jobId), card);
  void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
  void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  void queryClient.invalidateQueries({ queryKey: MOVE_REQUIREMENTS_PREFIX });
}

export function useRecommendationCard(candidateId: number, jobId: number, enabled = true) {
  return useQuery({
    queryKey: recommendationCardQueryKey(candidateId, jobId),
    queryFn: ({ signal }) => recommendationCardsApi.get(candidateId, jobId, signal),
    enabled,
    staleTime: 15_000,
  });
}

export function useSaveRecommendationCard(candidateId: number, jobId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CardSaveInput) => recommendationCardsApi.save(candidateId, jobId, input),
    onSuccess: (card) => refreshCardDependents(queryClient, candidateId, jobId, card),
  });
}

/** Zaznaczenie „Odpowiedź narusza deal-breaker” przy pytaniu karty. Ostrzeżenie
 *  w „Przesuń dalej” liczy serwer z tego samego zapisu. */
export function useSetDealBreakerHit(candidateId: number, jobId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ questionId, hit }: { questionId: string | number; hit: boolean }) =>
      recommendationCardsApi.setDealBreakerHit(candidateId, jobId, questionId, hit),
    onSuccess: (card) => refreshCardDependents(queryClient, candidateId, jobId, card),
  });
}

/** Zapis pozycji z notatki — odświeża kartę i arkusz screeningu pary. */
export function useApplyNote(candidateId: number, jobId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: NoteApplyInput) => recommendationCardsApi.applyNote(candidateId, jobId, input),
    onSuccess: (card) => {
      refreshCardDependents(queryClient, candidateId, jobId, card);
      void queryClient.invalidateQueries({ queryKey: ["screening-v2"] });
      void queryClient.invalidateQueries({ queryKey: ["pipeline-stage-screening"] });
      void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.screeningAnswersRoot(candidateId) });
    },
  });
}
