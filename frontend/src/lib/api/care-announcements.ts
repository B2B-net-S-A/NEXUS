// Opieka → Komunikaty do konsultantów (O12, 17.10.2026).
//
// Lustro `backend/app/api/care_announcements.py` (prefiks `/api/care/announcements`).
// Kto pisze, kto zatwierdza, zakres klientów Delivery Leada i stan przełącznika
// wysyłki liczy serwer (`me`, `settings`, `can_*`); front pokazuje to, co dostał.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type AnnouncementKind = "mandatory" | "informational";
export type AnnouncementStatus = "draft" | "pending" | "queued" | "sent" | "cancelled";
export type AudienceGroup = "all" | "client" | "owner" | "form" | "ending" | "selected";
export type AnnouncementForm = "b2b" | "uop" | "zlecenie";
export type RecipientStatus =
  | "pending"
  | "sending"
  | "sent"
  | "failed"
  | "uncertain"
  | "bounced"
  | "excluded_no_email"
  | "excluded_opted_out"
  | "cancelled";
export type Transport = "off" | "simulate" | "live" | "unconfigured";

export interface Audience {
  group: AudienceGroup;
  client_ids?: number[];
  owner_user_ids?: number[];
  forms?: AnnouncementForm[];
  ending_days?: number;
  candidate_ids?: number[];
}

export interface PersonRef {
  id: number;
  name: string;
}

export type RecipientCounts = Record<RecipientStatus | "unsubscribed", number>;

export interface AnnouncementRow {
  id: number;
  marker: string;
  kind: AnnouncementKind;
  status: AnnouncementStatus;
  subject: string;
  author: PersonRef | null;
  audience: Audience;
  audience_label: string;
  recipient_count: number;
  requires_approval: boolean;
  approver: PersonRef | null;
  created_at: string | null;
  submitted_at: string | null;
  approved_at: string | null;
  queued_at: string | null;
  send_started_at: string | null;
  send_finished_at: string | null;
  cancelled_at: string | null;
  counts: RecipientCounts;
  replies: { reply: number; bounce: number };
  can_approve: boolean;
}

export interface AnnouncementRecipient {
  candidate_id: number;
  contract_id: number | null;
  client_id: number | null;
  client_name: string | null;
  name: string;
  email: string | null;
  owner_name: string | null;
  status: RecipientStatus;
  error_code?: string | null;
  sent_at?: string | null;
  unsubscribed?: boolean;
  simulated?: boolean;
}

export interface AnnouncementReplyCase {
  case_id: number;
  kind: "reply" | "bounce";
  title: string;
  case_status: string;
  created_at: string | null;
}

export interface AnnouncementDetail extends AnnouncementRow {
  body: string;
  content_version: number;
  tested_at: string | null;
  test_current: boolean;
  return_note: string | null;
  submitted_by: PersonRef | null;
  recipients: AnnouncementRecipient[];
  reply_cases: AnnouncementReplyCase[];
  can_edit: boolean;
  can_test: boolean;
  can_submit: boolean;
  can_cancel: boolean;
  /** „Wyślij ponownie do nieudanych” (wysłany / w wysyłce, ktoś z błędem). */
  can_retry_failed?: boolean;
}

export interface AnnouncementSettings {
  sending_enabled: boolean;
  transport: Transport;
  sender: string | null;
  approval_threshold: number;
  rate_per_minute: number;
}

export interface AnnouncementList {
  items: AnnouncementRow[];
  me: { user_id: number; can_author: boolean; can_approve: boolean; is_admin: boolean };
  settings: AnnouncementSettings;
}

export interface AudienceOptions {
  clients: { id: number; name: string; consultants: number }[];
  owners: { id: number; name: string; consultants: number }[];
  forms: { value: AnnouncementForm; label: string; consultants: number }[];
  consultants: { candidate_id: number; name: string; client_name: string }[];
  total: number;
}

export interface AudiencePreview {
  total: number;
  will_receive: number;
  excluded_no_email: number;
  excluded_opted_out: number;
  requires_approval: boolean;
  rows: (AnnouncementRecipient & { form: AnnouncementForm; end_date: string | null })[];
}

export interface AnnouncementDraft {
  kind: AnnouncementKind;
  subject: string;
  body: string;
  audience: Audience;
}

const BASE = "/api/care/announcements";

export const announcementKeys = {
  all: ["care", "announcements"] as const,
  list: ["care", "announcements", "list"] as const,
  options: ["care", "announcements", "options"] as const,
  detail: (id: number) => ["care", "announcements", "detail", id] as const,
  /** `announcementId` — podgląd zapisanego komunikatu (zakres jego autora). */
  preview: (kind: AnnouncementKind, audience: Audience, announcementId: number | null = null) =>
    ["care", "announcements", "preview", kind, audienceKey(audience), announcementId] as const,
};

/** Grupa bez parametrów, których wymaga (np. klient bez wybranego klienta). */
export function audienceComplete(audience: Audience): boolean {
  switch (audience.group) {
    case "client":
      return (audience.client_ids?.length ?? 0) > 0;
    case "owner":
      return (audience.owner_user_ids?.length ?? 0) > 0;
    case "form":
      return (audience.forms?.length ?? 0) > 0;
    case "ending":
      return Number.isInteger(audience.ending_days) && (audience.ending_days ?? 0) >= 1;
    case "selected":
      return (audience.candidate_ids?.length ?? 0) > 0;
    default:
      return true;
  }
}

/** Tylko pola grupy, którą wybrano — klucz zapytania nie zależy od reszty. */
export function normalizeAudience(audience: Audience): Audience {
  switch (audience.group) {
    case "client":
      return { group: "client", client_ids: [...(audience.client_ids ?? [])].sort((a, b) => a - b) };
    case "owner":
      return {
        group: "owner",
        owner_user_ids: [...(audience.owner_user_ids ?? [])].sort((a, b) => a - b),
      };
    case "form":
      return { group: "form", forms: [...(audience.forms ?? [])].sort() };
    case "ending":
      return { group: "ending", ending_days: audience.ending_days };
    case "selected":
      return {
        group: "selected",
        candidate_ids: [...(audience.candidate_ids ?? [])].sort((a, b) => a - b),
      };
    default:
      return { group: "all" };
  }
}

function audienceKey(audience: Audience): string {
  return JSON.stringify(normalizeAudience(audience));
}

export function useAnnouncements(enabled = true) {
  return useQuery({
    queryKey: announcementKeys.list,
    queryFn: async () => (await api.get<AnnouncementList>(BASE)).data,
    staleTime: 15_000,
    enabled,
  });
}

export function useAnnouncement(id: number | null) {
  return useQuery({
    queryKey: announcementKeys.detail(id ?? 0),
    queryFn: async () => (await api.get<AnnouncementDetail>(`${BASE}/${id}`)).data,
    enabled: id !== null,
    staleTime: 10_000,
  });
}

export function useAudienceOptions(enabled = true) {
  return useQuery({
    queryKey: announcementKeys.options,
    queryFn: async () => (await api.get<AudienceOptions>(`${BASE}/options`)).data,
    enabled,
    staleTime: 60_000,
  });
}

/**
 * Odbiorcy grupy. Przy zapisanym komunikacie (`announcementId`) serwer liczy
 * w zakresie jego autora — tak samo jak „Wyślij” (admin przy szkicu Delivery
 * Leada widzi jego portfel, nie całą firmę).
 */
export function useAudiencePreview(
  kind: AnnouncementKind,
  audience: Audience,
  announcementId: number | null = null,
) {
  const ready = audienceComplete(audience);
  return useQuery({
    queryKey: announcementKeys.preview(kind, audience, announcementId),
    queryFn: async () =>
      (
        await api.post<AudiencePreview>(`${BASE}/preview`, {
          kind,
          audience: normalizeAudience(audience),
          ...(announcementId !== null ? { announcement_id: announcementId } : {}),
        })
      ).data,
    enabled: ready,
    staleTime: 30_000,
  });
}

function useAnnouncementMutation<TVars>(
  call: (vars: TVars) => Promise<AnnouncementDetail>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (detail) => {
      qc.setQueryData(announcementKeys.detail(detail.id), detail);
      qc.invalidateQueries({ queryKey: announcementKeys.list });
    },
  });
}

export function useCreateAnnouncement() {
  return useAnnouncementMutation(async (draft: AnnouncementDraft) => {
    const payload = { ...draft, audience: normalizeAudience(draft.audience) };
    return (await api.post<AnnouncementDetail>(BASE, payload)).data;
  });
}

export function useUpdateAnnouncement() {
  return useAnnouncementMutation(
    async ({ id, ...changes }: Partial<AnnouncementDraft> & { id: number }) => {
      const payload = changes.audience
        ? { ...changes, audience: normalizeAudience(changes.audience) }
        : changes;
      return (await api.patch<AnnouncementDetail>(`${BASE}/${id}`, payload)).data;
    },
  );
}

export type AnnouncementStep = "test-send" | "submit" | "approve" | "cancel" | "retry-failed";

export function useAnnouncementStep(step: AnnouncementStep) {
  return useAnnouncementMutation(
    async (id: number) => (await api.post<AnnouncementDetail>(`${BASE}/${id}/${step}`)).data,
  );
}

export function useReturnAnnouncement() {
  return useAnnouncementMutation(
    async ({ id, note }: { id: number; note: string | null }) =>
      (await api.post<AnnouncementDetail>(`${BASE}/${id}/return`, { note })).data,
  );
}

export function useAnnouncementSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (sendingEnabled: boolean) =>
      (
        await api.put<AnnouncementSettings>(`${BASE}/settings`, {
          sending_enabled: sendingEnabled,
        })
      ).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: announcementKeys.all }),
  });
}
