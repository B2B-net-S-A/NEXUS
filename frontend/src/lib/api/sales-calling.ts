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
export type QueueSection = "callbacks" | "no_answer" | "meetings" | "new";

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
  /** Kto dzwoni: wypełnione w Tabeli (przy „Wszyscy” widać cudze rekordy). */
  assignee?: Ref | null;
  /** Ostatnia zmiana rekordu: kolumna „Ostatnia modyfikacja” w Tabeli (13.11.2026). */
  modified_at?: string | null;
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
  counts: {
    callbacks: number;
    no_answer: number;
    meetings: number;
    new: number;
    later: number;
  };
  callbacks: QueueItem[];
  /** „Nie odebrane”: osobna zakładka bez względu na datę (13.11.2026). */
  no_answer: QueueItem[];
  meetings: QueueItem[];
  new: QueueItem[];
  campaigns: Ref[];
  today_counts: DayCounts;
  yesterday: string;
  yesterday_counts: DayCounts;
  /** Osoby z otwartymi rekordami: wybór osoby nad kolejką (decyzja Artura 13.11.2026). */
  callers?: Ref[];
}

/** Widok „Tabela”: wszystkie rekordy osoby i liczniki filtrów po wyniku. */
export interface CallRecordTable {
  items: QueueItem[];
  total: number;
  counts: Partial<Record<RecordState, number>>;
  /** Osoby z rekordami w wybranym zakresie, do filtra „Kto dzwoni”. */
  callers?: Ref[];
}

/** „Moje” to rekordy zalogowanej osoby, „Wszyscy” każdego dzwoniącego (decyzja Artura 12.11.2026). */
export type CallRecordScope = "mine" | "all";

export interface CallRecordFilters {
  state: RecordState | null;
  campaignId: number | null;
  search: string;
  scope?: CallRecordScope;
  /** Tylko przy „Wszyscy”: rekordy jednej osoby. */
  callerId?: number | null;
  /** Daty powrotu od–do (ISO), filtr Tabeli z 13.11.2026. */
  callbackFrom?: string;
  callbackTo?: string;
  /** Strona Tabeli od zera (po 200 wierszy). */
  page?: number;
}

/** Tyle wierszy Tabeli na stronę (limit trasy `/records`). */
export const TABLE_PAGE_SIZE = 200;

/** Linia „Na liście dzwonienia” na karcie firmy: bez numeru telefonu. */
export interface CompanyCallRecord {
  record_id: number;
  campaign: Ref | null;
  assignee: Ref | null;
  person_name: string | null;
  state: RecordState | "do_not_contact";
  callback_on: string | null;
  last_outcome_at: string | null;
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
  /** „Oferta ogólna wysłana” bez ponownego kontaktu. */
  never?: boolean;
}

/** Dane kontaktowe rekordu z karty kolejki (13.11.2026). */
export interface RecordEditInput {
  record_id: number;
  person_name?: string | null;
  person_title?: string | null;
  phone?: string | null;
  email?: string | null;
  note?: string | null;
}

/** Statusy, które Tabela zmienia bez telefonu (poprawka zapisu). */
export type CorrectableState =
  "no_answer" | "call_back" | "offer_sent" | "bad_contact";

export interface StateChangeInput {
  record_id: number;
  state: CorrectableState;
  callback_on?: string;
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
  /** Komu trafi rekord: kolumna podziału („Bianca”) albo osoba z okna. */
  assignee?: Ref | null;
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
  queue: (campaignId: number | null, callerId: number | null = null) =>
    ["sales", "calling", "queue", campaignId, callerId] as const,
  reminders: (
    scope: CallRecordScope,
    callerId: number | null,
    until: string | null,
  ) => ["sales", "calling", "reminders", scope, callerId, until] as const,
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

/** Kolejka osoby: domyślnie zalogowanej, `callerId` to wybór osoby (decyzja Artura 13.11.2026). */
export function useCallQueue(
  campaignId: number | null,
  callerId: number | null = null,
) {
  return useQuery({
    queryKey: callingKeys.queue(campaignId, callerId),
    queryFn: async () =>
      (
        await api.get<CallQueue>("/api/sales/calling/queue", {
          params: {
            ...(campaignId === null ? {} : { campaign_id: campaignId }),
            ...(callerId === null ? {} : { caller_id: callerId }),
          },
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
            ...(filters.scope === "all" ? { scope: "all" } : {}),
            ...(filters.scope === "all" && filters.callerId
              ? { caller_id: filters.callerId }
              : {}),
            ...(filters.callbackFrom
              ? { callback_from: filters.callbackFrom }
              : {}),
            ...(filters.callbackTo ? { callback_to: filters.callbackTo } : {}),
            ...(filters.page ? { offset: filters.page * TABLE_PAGE_SIZE } : {}),
          },
        })
      ).data,
    placeholderData: keepPreviousData,
  });
}

/** Na czyjej liście dzwonienia jest firma (karta firmy). */
export function useCompanyCallRecords(companyId: number) {
  return useQuery({
    queryKey: ["sales", "calling", "company", companyId] as const,
    queryFn: async () =>
      (await api.get<CompanyCallRecord[]>(`/api/sales/calling/companies/${companyId}/records`)).data,
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

/** Dane kontaktowe z karty: poprawia rekord i kontakt w kartotece. */
export function useEditRecord() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async ({ record_id, ...payload }: RecordEditInput) =>
      (
        await api.patch<CallCard>(
          `/api/sales/calling/records/${record_id}`,
          payload,
        )
      ).data,
    onSuccess: invalidate,
  });
}

/** Zmiana statusu z Tabeli: poprawka bez telefonu w dzienniku i licznikach. */
export function useChangeState() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async ({ record_id, ...payload }: StateChangeInput) =>
      (
        await api.post<OutcomeResult>(
          `/api/sales/calling/records/${record_id}/state`,
          payload,
        )
      ).data,
    onSuccess: invalidate,
  });
}

/** „Przypomnienia”: terminy powrotów (Oddzwonić, oferta z ponownym kontaktem), od najwcześniejszego. */
export function useCallReminders(
  scope: CallRecordScope = "mine",
  callerId: number | null = null,
  until: string | null = null,
) {
  return useQuery({
    queryKey: callingKeys.reminders(scope, callerId, until),
    queryFn: async () =>
      (
        await api.get<QueueItem[]>("/api/sales/calling/reminders", {
          params: {
            ...(scope === "all" ? { scope: "all" } : {}),
            ...(scope === "all" && callerId ? { caller_id: callerId } : {}),
            ...(until ? { until } : {}),
          },
        })
      ).data,
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

// ── Przeniesienie Excela dzwoniących: arkusz = osoba, kolor = wynik (11.11.2026) ──

export interface ExcelSheetPlan {
  title: string;
  assignee_id: number | null;
  rows: number;
  states: Partial<Record<RecordState, number>>;
  review: number;
  fates: Partial<Record<ImportFate, number>>;
  addable: number;
  without_company: number;
  moved: number;
  days: number;
  duplicate_days: number;
  totals: { calls: number; talks: number; offers: number; meetings: number };
}

export interface ExcelPreview {
  sheets: ExcelSheetPlan[];
  people: Ref[];
}

export interface ExcelTransferInput {
  campaign_id: number;
  file: File;
  contact_source: string;
  /** Nazwa arkusza → osoba z „Sprzedaż: edycja”. */
  assignees: Record<string, number>;
}

function excelForm(input: ExcelTransferInput): FormData {
  const form = new FormData();
  form.append("file", input.file);
  form.append("contact_source", input.contact_source);
  form.append("assignees", JSON.stringify(input.assignees));
  return form;
}

/** Bieg na sucho przeniesienia: co stanie się z każdym arkuszem; niczego nie zapisuje. */
export function usePreviewExcel() {
  return useMutation({
    mutationFn: async (input: ExcelTransferInput) =>
      (
        await api.post<ExcelPreview>(
          `/api/sales/calling/campaigns/${input.campaign_id}/excel/preview`,
          excelForm(input),
          MULTIPART,
        )
      ).data,
  });
}

export function useTransferExcel() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: ExcelTransferInput) =>
      (
        await api.post<{ added: number; days: number }>(
          `/api/sales/calling/campaigns/${input.campaign_id}/excel`,
          excelForm(input),
          MULTIPART,
        )
      ).data,
    onSuccess: invalidate,
  });
}
