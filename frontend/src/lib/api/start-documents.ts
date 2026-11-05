// Dokumenty do startu (0649). Lustro `backend/app/api/start_documents.py`.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const BASE = "/api/start-documents";
// Bez tego nagłówka axios wysyła FormData jako JSON i serwer odpowiada 422.
const MULTIPART = { headers: { "Content-Type": "multipart/form-data" } };

export type StartDocKind = "file" | "pesel" | "agreement";
export type StartDocState = "missing" | "delivered" | "returned" | "not_applicable";
export type StartDocTone = "late" | "today" | "calm";

export interface ClientStartDoc {
  id: number;
  name: string;
  note: string | null;
  kind: StartDocKind;
  required: boolean;
  offset_days: number;
  link_url: string | null;
  fill_from_agreement: boolean;
  template_name: string | null;
}

export type ClientStartDocInput = Omit<ClientStartDoc, "id" | "template_name">;

export interface PairStartDoc extends ClientStartDoc {
  state: StartDocState;
  deadline: string | null;
  file_name: string | null;
  has_value: boolean;
  delivered_at: string | null;
  delivered_by_name: string | null;
  checked_at: string | null;
  checked_by_name: string | null;
  reason: string | null;
  reason_by_name: string | null;
}

export interface PairStartDocs {
  candidate_id: number;
  job_id: number;
  client_id: number;
  client_name: string;
  start_date: string | null;
  deadline: string | null;
  tone: StartDocTone;
  working: boolean;
  done: number;
  total: number;
  recruiter_name: string | null;
  delivery_lead_name: string | null;
  agreement_number: string | null;
  list_sent_at: string | null;
  items: PairStartDoc[];
  permissions: {
    can_work: boolean;
    can_review: boolean;
    can_download: boolean;
    can_view_pesel: boolean;
  };
}

export interface MineStartDocRow {
  candidate_id: number;
  job_id: number;
  candidate_name: string;
  job_title: string;
  client_name: string;
  agreement_number: string | null;
  start_date: string | null;
  deadline: string | null;
  tone: StartDocTone;
  working: boolean;
  done: number;
  total: number;
  missing: string[];
  to_check: string[];
  recruiter_name: string | null;
}

export interface MineStartDocs {
  role: "recruiter" | "delivery_lead";
  items: MineStartDocRow[];
}

/** Plakietka karty Tablicy (`services/start_documents.card_badges`). */
export interface CardStartDocs {
  done: number;
  total: number;
  missing: string[];
  start_date: string | null;
  deadline: string | null;
  tone: StartDocTone;
}

export interface ListMailPreview {
  to: string | null;
  subject: string;
  text: string;
  attachments: string[];
  mailbox_connected: boolean;
  list_sent_at: string | null;
}

export const startDocsKeys = {
  client: (clientId: number) => ["start-docs", "client", clientId] as const,
  pair: (candidateId: number, jobId: number) =>
    ["start-docs", "pair", candidateId, jobId] as const,
  mine: ["start-docs", "mine"] as const,
  mail: (candidateId: number, jobId: number) =>
    ["start-docs", "mail", candidateId, jobId] as const,
};

function pairUrl(candidateId: number, jobId: number): string {
  return `${BASE}/pair/${candidateId}/${jobId}`;
}

export function itemUrl(
  candidateId: number,
  jobId: number,
  documentId: number,
  action: string,
): string {
  return `${pairUrl(candidateId, jobId)}/items/${documentId}/${action}`;
}

export function useClientStartDocs(clientId: number) {
  return useQuery({
    queryKey: startDocsKeys.client(clientId),
    queryFn: async () =>
      (await api.get<{ items: ClientStartDoc[] }>(`${BASE}/clients/${clientId}`)).data.items,
    retry: false,
  });
}

export function useSaveClientStartDoc(clientId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, input }: { id: number | null; input: ClientStartDocInput }) =>
      id === null
        ? (await api.post<ClientStartDoc>(`${BASE}/clients/${clientId}`, input)).data
        : (await api.patch<ClientStartDoc>(`${BASE}/items/${id}`, input)).data,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: startDocsKeys.client(clientId) }),
  });
}

export function useArchiveClientStartDoc(clientId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`${BASE}/items/${id}`);
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: startDocsKeys.client(clientId) }),
  });
}

export function useUploadStartDocTemplate(clientId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, file }: { id: number; file: File }) => {
      const body = new FormData();
      body.append("file", file);
      return (await api.put<ClientStartDoc>(`${BASE}/items/${id}/template`, body, MULTIPART)).data;
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: startDocsKeys.client(clientId) }),
  });
}

export function usePairStartDocs(candidateId: number, jobId: number, enabled = true) {
  return useQuery({
    queryKey: startDocsKeys.pair(candidateId, jobId),
    queryFn: async () =>
      (
        await api.get<PairStartDocs | null>(`${BASE}/pair`, {
          params: { candidate_id: candidateId, job_id: jobId },
        })
      ).data,
    enabled,
    retry: false,
    staleTime: 30_000,
  });
}

export function useMineStartDocs(enabled = true) {
  return useQuery({
    queryKey: startDocsKeys.mine,
    queryFn: async () => (await api.get<MineStartDocs>(`${BASE}/mine`)).data,
    enabled,
    retry: false,
    staleTime: 5 * 60_000,
  });
}

/** Każda zmiana stanu pary odświeża kartę, pulpit i pasek. */
export function usePairAction(candidateId: number, jobId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (run: () => Promise<PairStartDocs>) => run(),
    onSuccess: (state) => {
      queryClient.setQueryData(startDocsKeys.pair(candidateId, jobId), state);
      void queryClient.invalidateQueries({ queryKey: startDocsKeys.mine });
      // Plakietka karty: Tablica trzyma klucz i z liczbą, i z tekstem.
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
    },
  });
}

export const startDocsApi = {
  uploadFile: async (candidateId: number, jobId: number, documentId: number, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return (
      await api.put<PairStartDocs>(itemUrl(candidateId, jobId, documentId, "file"), body, MULTIPART)
    ).data;
  },
  savePesel: async (candidateId: number, jobId: number, documentId: number, pesel: string) =>
    (
      await api.put<PairStartDocs>(itemUrl(candidateId, jobId, documentId, "pesel"), { pesel })
    ).data,
  readPesel: async (candidateId: number, jobId: number, documentId: number) =>
    (await api.get<{ pesel: string }>(itemUrl(candidateId, jobId, documentId, "pesel"))).data
      .pesel,
  check: async (candidateId: number, jobId: number, documentId: number) =>
    (await api.post<PairStartDocs>(itemUrl(candidateId, jobId, documentId, "check"))).data,
  returnItem: async (candidateId: number, jobId: number, documentId: number, reason: string) =>
    (
      await api.post<PairStartDocs>(itemUrl(candidateId, jobId, documentId, "return"), {
        reason,
      })
    ).data,
  notApplicable: async (
    candidateId: number,
    jobId: number,
    documentId: number,
    reason: string,
  ) =>
    (
      await api.post<PairStartDocs>(itemUrl(candidateId, jobId, documentId, "not-applicable"), {
        reason,
      })
    ).data,
  reset: async (candidateId: number, jobId: number, documentId: number) =>
    (await api.delete<PairStartDocs>(itemUrl(candidateId, jobId, documentId, "state"))).data,
  remind: async (candidateId: number, jobId: number) =>
    (await api.post<{ sent: boolean }>(`${pairUrl(candidateId, jobId)}/remind`)).data,
  mailPreview: async (candidateId: number, jobId: number) =>
    (await api.get<ListMailPreview>(`${pairUrl(candidateId, jobId)}/list-mail`)).data,
  mailSend: async (candidateId: number, jobId: number) =>
    (await api.post<{ sent: boolean }>(`${pairUrl(candidateId, jobId)}/list-mail`)).data,
};
