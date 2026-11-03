// Portal konsultanta od strony back office'u: lustro `backend/app/api/consultant_portal_staff.py`.
// Ocenę rozmowy serwer zwraca tylko kierownikowi i nigdy osobie ocenianej.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { boKeys } from "@/lib/api/back-office";

const BASE = "/api/back-office/portal";

export type PortalTopicKey = "invoice" | "contract" | "leave" | "access" | "next" | "data";

export interface PortalStatus {
  state: "off" | "pilot" | "all";
  pilot_contract_ids: number[];
  booking_ready: boolean;
  sms_available: boolean;
  mailbox: {
    configured: boolean;
    last_run_at: string | null;
    last_status: string | null;
    last_error: string | null;
  } | null;
  viewer: { is_lead: boolean; user_id: number };
}

export interface StaffFaqItem {
  id: number;
  topic: PortalTopicKey;
  question: string;
  answer: string;
  position: number;
  published: boolean;
}

export interface StaffFaq {
  items: StaffFaqItem[];
  topics: { key: PortalTopicKey; label: string }[];
}

export type StaffFaqInput = Omit<StaffFaqItem, "id">;

export interface MeetingRating {
  score: number;
  resolved: boolean | null;
  comment: string | null;
  followup_status: "none" | "open" | "done";
}

export interface StaffMeeting {
  id: number;
  consultant: string | null;
  client: string | null;
  host: string | null;
  host_user_id: number | null;
  topic: PortalTopicKey;
  topic_label: string;
  reason: string | null;
  start_at: string;
  end_at: string;
  status: "booked" | "cancelled";
  case_id: number | null;
  transcript_status: string;
  summary_status: string;
  rating: MeetingRating | null;
}

export interface StaffMeetingDetail extends StaffMeeting {
  summary: string | null;
  action_items: { who: string; what: string }[];
  transcript: string | null;
  transcript_purged: boolean;
}

export interface QualityPerson {
  user_id: number;
  name: string;
  meetings: number;
  rated: number;
  average: number | null;
  low: number;
  median_take_minutes: number | null;
}

export interface QualityTask {
  id: number;
  meeting_id: number;
  score: number;
  comment: string | null;
  resolved: boolean | null;
  due_on: string | null;
  consultant: string | null;
  host: string | null;
  start_at: string;
}

export interface QualityReport {
  days: number;
  meetings: number;
  rated: number;
  average: number | null;
  resolved_share: number | null;
  people: QualityPerson[];
  tasks: QualityTask[];
}

export interface MyReview {
  year: number;
  month: number;
  month_label: string;
  enough: boolean;
  min_for_review: number;
  rated: number | null;
  average: number | null;
  resolved_share: number | null;
}

export interface StaffDocument {
  id: number;
  kind: "report" | "invoice";
  status: "received" | "accepted" | "rejected" | "paid";
  file_name: string | null;
  channel: "portal" | "mailbox";
  created_at: string;
  reject_reason: string | null;
  contract_id: number | null;
  period_year: number;
  period_month: number;
  period_guessed: boolean;
  sender_email: string | null;
  invoice_signal_at: string | null;
}

export const portalStaffKeys = {
  all: ["portal-staff"] as const,
  status: ["portal-staff", "status"] as const,
  faq: ["portal-staff", "faq"] as const,
  meetings: ["portal-staff", "meetings"] as const,
  meeting: (id: number) => ["portal-staff", "meeting", id] as const,
  quality: ["portal-staff", "quality"] as const,
  review: ["portal-staff", "review"] as const,
  cardDocuments: (cardId: number) => ["portal-staff", "card-documents", cardId] as const,
};

export function usePortalStatus() {
  return useQuery({
    queryKey: portalStaffKeys.status,
    queryFn: async () => (await api.get<PortalStatus>(`${BASE}/status`)).data,
  });
}

export function useStaffFaq() {
  return useQuery({
    queryKey: portalStaffKeys.faq,
    queryFn: async () => (await api.get<StaffFaq>(`${BASE}/faq`)).data,
  });
}

export function useSaveFaq() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, input }: { id: number | null; input: StaffFaqInput }) =>
      id == null
        ? (await api.post<StaffFaqItem>(`${BASE}/faq`, input)).data
        : (await api.put<StaffFaqItem>(`${BASE}/faq/${id}`, input)).data,
    onSuccess: () => client.invalidateQueries({ queryKey: portalStaffKeys.faq }),
  });
}

export function useDeleteFaq() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`${BASE}/faq/${id}`);
    },
    onSuccess: () => client.invalidateQueries({ queryKey: portalStaffKeys.faq }),
  });
}

export function useStaffMeetings() {
  return useQuery({
    queryKey: portalStaffKeys.meetings,
    queryFn: async () => (await api.get<{ items: StaffMeeting[] }>(`${BASE}/meetings`)).data,
  });
}

export function useStaffMeeting(id: number | null) {
  return useQuery({
    queryKey: portalStaffKeys.meeting(id ?? 0),
    enabled: id != null,
    queryFn: async () => (await api.get<StaffMeetingDetail>(`${BASE}/meetings/${id}`)).data,
  });
}

export function useQualityReport(enabled: boolean) {
  return useQuery({
    queryKey: portalStaffKeys.quality,
    enabled,
    queryFn: async () => (await api.get<QualityReport>(`${BASE}/quality`)).data,
  });
}

export function useMyReview() {
  return useQuery({
    queryKey: portalStaffKeys.review,
    queryFn: async () => (await api.get<MyReview>(`${BASE}/quality/my-review`)).data,
  });
}

export function useCloseQualityTask() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, note }: { id: number; note: string }) =>
      (await api.post(`${BASE}/quality/tasks/${id}/close`, { note })).data,
    onSuccess: () => client.invalidateQueries({ queryKey: portalStaffKeys.quality }),
  });
}

export function useCardDocuments(cardId: number | null) {
  return useQuery({
    queryKey: portalStaffKeys.cardDocuments(cardId ?? 0),
    enabled: cardId != null,
    queryFn: async () =>
      (await api.get<{ items: StaffDocument[] }>(`${BASE}/documents/by-card/${cardId}`)).data,
  });
}

export function useDocumentDecision() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      action,
      body,
    }: {
      id: number;
      action: "accept" | "reject" | "paid" | "assign";
      body?: Record<string, unknown>;
    }) => (await api.post<StaffDocument>(`${BASE}/documents/${id}/${action}`, body ?? {})).data,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: portalStaffKeys.all });
      client.invalidateQueries({ queryKey: boKeys.all });
    },
  });
}

export async function downloadStaffDocument(document_: StaffDocument): Promise<void> {
  const response = await api.get<Blob>(`${BASE}/documents/${document_.id}/file`, {
    responseType: "blob",
  });
  const url = URL.createObjectURL(response.data);
  const link = window.document.createElement("a");
  link.href = url;
  link.download = document_.file_name ?? "dokument";
  link.click();
  URL.revokeObjectURL(url);
}
