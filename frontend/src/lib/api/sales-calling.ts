// Sprzedaż → Dzwonienie: kolejka, wynik rozmowy, kampanie i import listy
// (`/api/sales/calling`). Osobny plik, bo `sales.ts` ma już blisko 2000 linii.
// Klucze zaczynają się od "sales", więc każdy zapis w Sprzedaży odświeża też kolejkę.

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { ActivityKind, CallOutcome, QueueOnlyOutcome, Ref } from "@/lib/api/sales";

export type QueueOutcome =
  | "no_answer"
  | "call_back"
  | "not_now"
  | "offer_sent"
  | "meeting_booked"
  | "do_not_contact"
  | "not_interested"
  | "bad_contact";
export type RecordState = "new" | QueueOutcome;
export type QueueSection = "callbacks" | "meetings" | "new";

export interface QueueItem {
  key: string;
  section: QueueSection;
  record_id: number | null;
  opportunity_id: number | null;
  opportunity_title: string | null;
  company: Ref;
  campaign: Ref | null;
  person_name: string | null;
  person_title: string | null;
  phone: string | null;
  state: RecordState;
  due_on: string | null;
  attempts: number;
  last_outcome_at: string | null;
  since: string;
}

/** Licznik dnia bez celu: zastępuje ręczne „Podsumowanie” z Excela (11.11.2026). */
export interface DayCounts {
  calls: number;
  talks: number;
  offers: number;
  meetings: number;
}

export interface CallQueue {
  today: string;
  counts: { callbacks: number; meetings: number; new: number; later: number };
  callbacks: QueueItem[];
  meetings: QueueItem[];
  new: QueueItem[];
  campaigns: Ref[];
  today_counts: DayCounts;
  yesterday: string;
  yesterday_counts: DayCounts;
}

/** Widok „Tabela”: wszystkie rekordy osoby i liczniki filtrów po wyniku. */
export interface CallRecordTable {
  items: QueueItem[];
  total: number;
  counts: Partial<Record<RecordState, number>>;
}

export interface CallRecordFilters {
  state: RecordState | null;
  campaignId: number | null;
  search: string;
}

export interface CallHistoryEntry {
  kind: ActivityKind;
  direction: "in" | "out" | null;
  outcome: CallOutcome | QueueOnlyOutcome | null;
  subject: string | null;
  at: string;
}

export interface CallCard {
  company: Ref;
  domain: string | null;
  contact_id: number | null;
  email: string | null;
  contact_source: string | null;
  note: string | null;
  service: string | null;
  script: string | null;
  linkedin_url: string | null;
  do_not_contact: boolean;
  client_refusal: string | null;
  can_save: boolean;
  history: CallHistoryEntry[];
}

export interface OutcomeInput {
  item: Pick<QueueItem, "record_id" | "opportunity_id" | "campaign">;
  outcome: QueueOutcome;
  callback_on?: string;
  note?: string;
  /** Szansa założona z umówionego spotkania (rekord kampanii). */
  opportunity_id?: number;
  /** „Nie zainteresowany” bez powrotu do kolejki. */
  never?: boolean;
}

export interface OutcomeResult {
  record_id: number;
  state: RecordState;
  callback_on: string | null;
  opportunity_id: number | null;
}

export interface CallCampaign {
  id: number;
  name: string;
  service: string | null;
  script: string | null;
  total: number;
  counts: Partial<Record<RecordState, number>>;
}

export interface CampaignInput {
  name?: string;
  service?: string | null;
  script?: string | null;
}

export type ImportFate =
  | "new_company"
  | "linked"
  | "already_in_campaign"
  | "other_caller"
  | "client"
  | "do_not_contact"
  | "no_phone";

export interface ImportRow {
  line: number;
  company: string;
  person: string | null;
  title: string | null;
  phone: string | null;
  fate: ImportFate;
  detail: string;
  to_decide: boolean;
}

export interface ImportPreview {
  total: number;
  addable: number;
  to_decide: number;
  without_company: number;
  counts: Record<ImportFate, number>;
  rows: ImportRow[];
}

export interface ImportResult {
  added: number;
  total: number;
  without_company: number;
  counts: Record<ImportFate, number>;
}

export interface ImportInput {
  campaign_id: number;
  file: File;
  contact_source: string;
  assignee_user_id?: number;
}

export const callingKeys = {
  queue: (campaignId: number | null) => ["sales", "calling", "queue", campaignId] as const,
  card: (key: string) => ["sales", "calling", "card", key] as const,
  campaigns: ["sales", "calling", "campaigns"] as const,
  records: (filters: CallRecordFilters) => ["sales", "calling", "records", filters] as const,
};

function useInvalidateSales() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["sales"] });
}

/** Rekord kampanii ma własny adres; pozycja szansy idzie po szansie, nawet gdy ma już rekord. */
function itemPath(item: Pick<QueueItem, "record_id" | "opportunity_id" | "campaign">): string {
  return item.campaign !== null || item.opportunity_id === null
    ? `/api/sales/calling/records/${item.record_id}`
    : `/api/sales/calling/opportunities/${item.opportunity_id}`;
}

export function useCallQueue(campaignId: number | null) {
  return useQuery({
    queryKey: callingKeys.queue(campaignId),
    queryFn: async () =>
      (
        await api.get<CallQueue>("/api/sales/calling/queue", {
          params: campaignId === null ? {} : { campaign_id: campaignId },
        })
      ).data,
    placeholderData: keepPreviousData,
  });
}

export function useCallRecords(filters: CallRecordFilters) {
  return useQuery({
    queryKey: callingKeys.records(filters),
    queryFn: async () =>
      (
        await api.get<CallRecordTable>("/api/sales/calling/records", {
          params: {
            ...(filters.state === null ? {} : { state: filters.state }),
            ...(filters.campaignId === null ? {} : { campaign_id: filters.campaignId }),
            ...(filters.search.trim() ? { q: filters.search.trim() } : {}),
          },
        })
      ).data,
    placeholderData: keepPreviousData,
  });
}

export function useCallCard(item: QueueItem | null) {
  return useQuery({
    queryKey: callingKeys.card(item?.key ?? ""),
    queryFn: async () => (await api.get<CallCard>(itemPath(item as QueueItem))).data,
    enabled: item !== null,
  });
}

/** Wynik rozmowy z kolejki: zapisuje stan rekordu i telefon w dzienniku. */
export function useSaveOutcome() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async ({ item, ...payload }: OutcomeInput) =>
      (await api.post<OutcomeResult>(`${itemPath(item)}/outcome`, payload)).data,
    onSuccess: () => {
      void invalidate();
    },
  });
}

export function useCallCampaigns(enabled = true) {
  return useQuery({
    queryKey: callingKeys.campaigns,
    queryFn: async () => (await api.get<CallCampaign[]>("/api/sales/calling/campaigns")).data,
    enabled,
  });
}

export function useSaveCampaign() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async ({ id, ...payload }: CampaignInput & { id?: number }) =>
      (
        id === undefined
          ? await api.post<CallCampaign>("/api/sales/calling/campaigns", payload)
          : await api.patch<CallCampaign>(`/api/sales/calling/campaigns/${id}`, payload)
      ).data,
    onSuccess: invalidate,
  });
}

function importForm(input: ImportInput): FormData {
  const form = new FormData();
  form.append("file", input.file);
  form.append("contact_source", input.contact_source);
  if (input.assignee_user_id !== undefined) {
    form.append("assignee_user_id", String(input.assignee_user_id));
  }
  return form;
}

const MULTIPART = { headers: { "Content-Type": "multipart/form-data" } };

/** Los każdego wiersza listy przed zapisem; niczego nie zapisuje. */
export function usePreviewImport() {
  return useMutation({
    mutationFn: async (input: ImportInput) =>
      (
        await api.post<ImportPreview>(
          `/api/sales/calling/campaigns/${input.campaign_id}/import/preview`,
          importForm(input),
          MULTIPART,
        )
      ).data,
  });
}

export function useImportList() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: ImportInput) =>
      (
        await api.post<ImportResult>(
          `/api/sales/calling/campaigns/${input.campaign_id}/import`,
          importForm(input),
          MULTIPART,
        )
      ).data,
    onSuccess: invalidate,
  });
}
