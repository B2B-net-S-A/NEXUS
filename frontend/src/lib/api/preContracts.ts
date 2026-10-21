"use client";

/**
 * Umowa przedwstępna przy osobie w rekrutacji (0505, 21.10.2026).
 *
 * Lustro `backend/app/api/pre_contracts.py`. Stan, plakietkę i napisy liczy
 * serwer (`services/pre_contracts.badge`) — front tylko je pokazuje.
 * Reguła: `docs/claude/kontrakty/generator-umow-b2b-trzy-zakladki-cyklu-zycia-umowy.md`
 * (sekcja „Umowa przedwstępna w rekrutacji”).
 */

import { useQuery, type QueryClient } from "@tanstack/react-query";

import api from "@/lib/api";

export type PreContractNeededBefore =
  "cv_sent" | "client_interview" | "b2b_contract" | "date";

export type PreContractSignatureForm =
  | "trusted_profile"
  | "personal_signature"
  | "qualified"
  | "handwritten_scan"
  | "other";

export type PreContractWithdrawalKind =
  "no_show" | "refused" | "resigned" | "bypassed";

export type PreContractTone =
  "missing" | "late" | "wait" | "signer" | "ok" | "closed";

export interface PreContractBadge {
  state: string;
  label: string;
  tone: PreContractTone;
  detail: string;
}

/** Plakietka na karcie Tablicy (`KanbanItem.pre_contract`). */
export interface CardPreContract extends PreContractBadge {
  id: number;
}

export interface PersonRef {
  id: number;
  name: string;
}

export interface PreContractEvent {
  id: number;
  kind: string;
  label: string;
  at: string;
  actor?: PersonRef | null;
  payload?: Record<string, unknown> | null;
}

export interface PreContractWithdrawal {
  kind: PreContractWithdrawalKind;
  kind_label: string;
  event_on: string;
  note: string;
  decision_user_id?: number | null;
  decision?: "demand" | "waive" | null;
  decision_note?: string | null;
  contract_state?: { in_force?: boolean; valid_until?: string | null };
}

export interface PreContractRequest {
  id: number;
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string;
  client_id?: number | null;
  client_name?: string | null;
  state: string;
  state_label: string;
  badge: PreContractBadge;
  is_open: boolean;
  needed_before: PreContractNeededBefore;
  needed_before_label: string;
  needed_by?: string | null;
  reason?: string | null;
  requested_by?: PersonRef | null;
  requested_at: string;
  assignee?: PersonRef | null;
  watchers: PersonRef[];
  watching: boolean;
  document_id?: number | null;
  document_type?: string | null;
  sent_at?: string | null;
  candidate_signed_at?: string | null;
  candidate_signature_form?: PreContractSignatureForm | null;
  candidate_signature_form_label?: string | null;
  candidate_file_name?: string | null;
  company_signed_at?: string | null;
  company_file_name?: string | null;
  valid_until?: string | null;
  b2b_deadline?: string | null;
  closed_at?: string | null;
  close_reason?: string | null;
  withdrawal?: PreContractWithdrawal | null;
  column?: string | null;
  stage_name?: string | null;
  can_withdraw: boolean;
  can_decide_penalty: boolean;
  events: PreContractEvent[];
}

export interface PreContractPairDocument {
  id: number;
  document_type: string;
  document_date: string;
  status: string;
  signed: boolean;
  linked: boolean;
}

export interface PreContractPair {
  current: PreContractRequest | null;
  history: PreContractRequest[];
  documents: PreContractPairDocument[];
}

export type PreContractTab =
  "todo" | "mine" | "expiring" | "b2b" | "penalty" | "all";

export interface PreContractList {
  items: PreContractRequest[];
  counts: Record<PreContractTab, number>;
}

export interface CreatePreContractBody {
  candidate_id: number;
  job_id: number;
  needed_before: PreContractNeededBefore;
  needed_by?: string | null;
  reason?: string | null;
  assignee_id?: number | null;
}

export const NEEDED_BEFORE_OPTIONS: ReadonlyArray<{
  value: PreContractNeededBefore;
  label: string;
}> = [
  { value: "cv_sent", label: "Przed wysłaniem CV" },
  { value: "client_interview", label: "Przed rozmową u klienta" },
  { value: "b2b_contract", label: "Przed umową B2B" },
  { value: "date", label: "Do daty…" },
];

export const SIGNATURE_FORM_OPTIONS: ReadonlyArray<{
  value: PreContractSignatureForm;
  label: string;
}> = [
  { value: "trusted_profile", label: "Profil zaufany" },
  { value: "personal_signature", label: "Podpis osobisty (e-dowód)" },
  { value: "qualified", label: "Kwalifikowany" },
  { value: "handwritten_scan", label: "Odręcznie, skan" },
  { value: "other", label: "Inaczej" },
];

export const WITHDRAWAL_OPTIONS: ReadonlyArray<{
  value: PreContractWithdrawalKind;
  label: string;
}> = [
  { value: "no_show", label: "Nie przyszedł na rozmowę albo test" },
  { value: "refused", label: "Odmówił udziału" },
  { value: "resigned", label: "Zrezygnował w trakcie" },
  { value: "bypassed", label: "Poszedł do klienta inną drogą" },
];

export const PRE_CONTRACT_TABS: ReadonlyArray<{
  value: PreContractTab;
  label: string;
}> = [
  { value: "todo", label: "Do zrobienia" },
  { value: "mine", label: "Moje prośby" },
  { value: "expiring", label: "Wygasają w 7 dni" },
  { value: "b2b", label: "Termin umowy B2B" },
  { value: "penalty", label: "Do decyzji o karze" },
  { value: "all", label: "Wszystkie" },
];

/** Klasy tonu plakietki — tylko tokeny (CLAUDE.md, „kolory wyłącznie z tokenów”). */
export const PRE_CONTRACT_TONE_CLASS: Record<PreContractTone, string> = {
  missing: "bg-warning/15 text-warning",
  late: "bg-destructive/10 text-destructive",
  wait: "bg-info/15 text-info",
  signer: "bg-muted text-muted-foreground",
  ok: "bg-success/15 text-success",
  closed: "bg-muted text-muted-foreground",
};

const base = "/api/pre-contracts";

export const preContractsApi = {
  pair: async (candidateId: number, jobId: number) =>
    (
      await api.get<PreContractPair>(`${base}/pair`, {
        params: { candidate_id: candidateId, job_id: jobId },
      })
    ).data,
  list: async (tab: PreContractTab) =>
    (await api.get<PreContractList>(base, { params: { tab } })).data,
  create: async (body: CreatePreContractBody) =>
    (await api.post<PreContractRequest>(base, body)).data,
  update: async (
    id: number,
    body: Partial<
      Pick<CreatePreContractBody, "needed_before" | "needed_by" | "assignee_id">
    >,
  ) => (await api.patch<PreContractRequest>(`${base}/${id}`, body)).data,
  linkDocument: async (id: number, documentId: number) =>
    (
      await api.post<PreContractRequest>(`${base}/${id}/document`, {
        document_id: documentId,
      })
    ).data,
  markSent: async (id: number, note?: string) =>
    (
      await api.post<PreContractRequest>(`${base}/${id}/sent`, {
        note: note || null,
      })
    ).data,
  candidateSigned: async (
    id: number,
    form: PreContractSignatureForm,
    file: File,
  ) => {
    const data = new FormData();
    data.append("signature_form", form);
    data.append("file", file);
    return (
      await api.post<PreContractRequest>(
        `${base}/${id}/candidate-signed`,
        data,
        {
          // Domyślny nagłówek `api` to JSON — axios zserializowałby FormData.
          headers: { "Content-Type": "multipart/form-data" },
        },
      )
    ).data;
  },
  companySigned: async (id: number, file: File) => {
    const data = new FormData();
    data.append("file", file);
    return (
      await api.post<PreContractRequest>(`${base}/${id}/company-signed`, data, {
        // Domyślny nagłówek `api` to JSON — axios zserializowałby FormData.
        headers: { "Content-Type": "multipart/form-data" },
      })
    ).data;
  },
  downloadFile: async (id: number, kind: "candidate" | "company") =>
    api.get<Blob>(`${base}/${id}/files/${kind}`, { responseType: "blob" }),
  watch: async (id: number) =>
    (await api.post<PreContractRequest>(`${base}/${id}/watch`)).data,
  unwatch: async (id: number) =>
    (await api.delete<PreContractRequest>(`${base}/${id}/watch`)).data,
  withdraw: async (id: number) =>
    (await api.post<PreContractRequest>(`${base}/${id}/withdraw`)).data,
  cancel: async (id: number, reason: string) =>
    (await api.post<PreContractRequest>(`${base}/${id}/cancel`, { reason }))
      .data,
  candidateRefused: async (id: number, reason: string) =>
    (
      await api.post<PreContractRequest>(`${base}/${id}/candidate-refused`, {
        reason,
      })
    ).data,
  fulfilled: async (id: number) =>
    (await api.post<PreContractRequest>(`${base}/${id}/fulfilled`)).data,
  candidateWithdrew: async (
    id: number,
    body: {
      kind: PreContractWithdrawalKind;
      event_on: string;
      note: string;
      decision_user_id?: number | null;
    },
  ) =>
    (
      await api.post<PreContractRequest>(
        `${base}/${id}/candidate-withdrew`,
        body,
      )
    ).data,
  penaltyDecision: async (
    id: number,
    decision: "demand" | "waive",
    note?: string,
  ) =>
    (
      await api.post<PreContractRequest>(`${base}/${id}/penalty-decision`, {
        decision,
        note: note || null,
      })
    ).data,
};

export const preContractPairKey = (candidateId: number, jobId: number) =>
  ["pre-contract", "pair", candidateId, jobId] as const;

export function usePreContractPair(
  candidateId: number | null,
  jobId: number | null,
) {
  return useQuery({
    queryKey: preContractPairKey(candidateId ?? 0, jobId ?? 0),
    queryFn: () => preContractsApi.pair(candidateId as number, jobId as number),
    enabled: candidateId != null && jobId != null,
    staleTime: 30_000,
  });
}

export function usePreContractList(tab: PreContractTab) {
  return useQuery({
    queryKey: ["pre-contract", "list", tab] as const,
    queryFn: () => preContractsApi.list(tab),
    staleTime: 30_000,
  });
}

/** Po każdym kroku: panel pary, lista, Tablica rekrutacji (plakietka). */
export function invalidatePreContract(
  queryClient: QueryClient,
  jobId: number,
): void {
  void queryClient.invalidateQueries({ queryKey: ["pre-contract"] });
  void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
  void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
}

/** Link do Generatora dokumentów z wybraną parą (kreator „Nowy dokument”). */
export function generatorPreliminaryHref(
  candidateId: number,
  jobId: number,
): string {
  const params = new URLSearchParams({
    tab: "documents",
    new: "preliminary",
    candidate: String(candidateId),
    job: String(jobId),
  });
  return `/contracts/b2b-generator?${params.toString()}`;
}
