// Stawki pary, których nie ma na etapie, a leżą w notatkach (12.10.2026).
//
// Backend: `services/recruitment_rate_hints.py`. Para z czasów Traffita ma
// etapy bez kwot — oczekiwanie kandydata jest w karcie rekomendacji, cena
// wysłania w notatce Delivery Leada z dnia wysyłki. To PODPOWIEDZI: stawką
// stają się dopiero po zapisie w polu. Zakładka „Rekrutacje” profilu dostaje
// je w `/history`, panel osoby na Tablicy — z trasy niżej. Notatkę z wysyłki
// serwer oddaje tylko rolom, które widzą stawkę do klienta.

import api from "@/lib/api";
import { dayText, hourlyText, rateSourceLabel } from "@/lib/candidate-rate";

export interface ExpectedRateHint {
  amount_hourly: number | string;
  raw: string | null;
  at: string | null;
  source: string;
  author_name: string | null;
}

export interface ClientRateNote {
  note_id: number;
  text: string;
  at: string | null;
  author_name: string | null;
}

export interface RecruitmentRateHints {
  candidate_id: number;
  job_id: number;
  expected_rate_hint: ExpectedRateHint | null;
  client_rate_note: ClientRateNote | null;
}

export const recruitmentRateHintsQueryKey = (candidateId: number, jobId: number) =>
  ["recruitment-rate-hints", candidateId, jobId] as const;

export async function fetchRecruitmentRateHints(
  candidateId: number,
  jobId: number,
): Promise<RecruitmentRateHints> {
  const { data } = await api.get<RecruitmentRateHints>(
    `/api/candidates/${candidateId}/recruitment-rate-hints`,
    { params: { job_id: jobId } },
  );
  return data;
}

/** „90 zł/h” — kwota podpowiedzi albo `null`, gdy serwer jej nie przysłał. */
export function expectedRateHintText(
  hint: ExpectedRateHint | null | undefined,
): string | null {
  return hint ? hourlyText(hint.amount_hourly) : null;
}

/** „Screening (z notatki) · Anna Nowak · 21.09.2026” — skąd jest kwota. */
export function expectedRateHintCaption(hint: ExpectedRateHint): string {
  return [rateSourceLabel(hint.source), hint.author_name, dayText(hint.at)]
    .filter(Boolean)
    .join(" · ");
}

/** „Notatka z wysyłki · Anna Nowak · 22.09.2026”. */
export function clientRateNoteCaption(note: ClientRateNote): string {
  return ["Notatka z wysyłki", note.author_name, dayText(note.at)]
    .filter(Boolean)
    .join(" · ");
}
