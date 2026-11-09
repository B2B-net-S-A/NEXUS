/** Rekrutacja własna: lustro `/api/own-hiring`. */
import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";

export type OwnHiringStage =
  | "new"
  | "invited"
  | "no_response"
  | "assistant"
  | "teams"
  | "office"
  | "contract"
  | "signed"
  | "closed";
export type OwnHiringBucket = "match" | "review" | "filtered";

export interface OwnHiringBooking {
  kind: "teams" | "office";
  start: string;
  end: string;
  via: "link" | "assistant" | "owner";
  sync_status: "pending" | "ok" | "failed";
  join_url: string | null;
}

export interface OwnHiringCard {
  id: number;
  candidate_id: number;
  name: string;
  city: string | null;
  stage: OwnHiringStage;
  bucket: OwnHiringBucket;
  filter_reason: string | null;
  role: string | null;
  company: string | null;
  months: number | null;
  until: string | null;
  is_it: boolean;
  source: string | null;
  ad_title: string | null;
  applied_at: string;
  has_email: boolean;
  invited_at: string | null;
  response_due_at: string | null;
  replied_at: string | null;
  call_attempts: number;
  callback_at: string | null;
  booking: OwnHiringBooking | null;
  needs_decision: boolean;
  contract_sent_at: string | null;
  signed_at: string | null;
  close_reason: string | null;
}

export interface OwnHiringDetail extends OwnHiringCard {
  email: string | null;
  phone: string | null;
  availability: string | null;
  expected_money: string | null;
  tech_level: string | null;
  teams_note: string | null;
  office_note: string | null;
  contract_kind: string | null;
  events: { kind: string; at: string; payload: Record<string, unknown> }[];
}

export interface OwnHiringBoard {
  cards: OwnHiringCard[];
  new_counts: Record<OwnHiringBucket, number>;
  closed_counts: Record<string, number>;
  last_import_at: string | null;
}

export interface OwnHiringSettings {
  windows: Record<string, string[][]>;
  slot_minutes: number;
  office_minutes: number;
  buffer_minutes: number;
  lead_hours: number;
  horizon_days: number;
  response_business_days: number;
  office_address: string;
}

export interface OwnHiringProcess {
  id: number;
  title: string;
  ad_titles: string[];
  assistant_user_id: number | null;
  settings: OwnHiringSettings;
  intake_since: string;
}

export interface SlotDay {
  date: string;
  label: string;
  slots: string[];
}

export interface OwnHiringSlots {
  calendar_available: boolean;
  days: SlotDay[];
}

export interface QueueItem {
  id: number;
  name: string;
  phone: string | null;
  ad_title: string | null;
  invited_at: string | null;
  handed_off_at: string | null;
  call_attempts: number;
  callback_at: string | null;
  max_attempts: number;
}

export interface InvitationPreview {
  subject: string;
  body_text: string;
  response_due_at: string;
}

export interface InviteResult {
  id: number;
  outcome: "sent" | "no_email" | "failed" | "wrong_stage";
}

export interface OwnHiringMe {
  role: "owner" | "assistant" | null;
  can_create: boolean;
}

const BASE = "/api/own-hiring";

export const ownHiringKeys = {
  all: ["own-hiring"] as const,
  me: ["own-hiring", "me"] as const,
};

async function get<T>(path: string): Promise<T> {
  return (await api.get<T>(`${BASE}${path}`)).data;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  return (await api.post<T>(`${BASE}${path}`, body ?? {})).data;
}

export const ownHiringApi = {
  me: () => get<OwnHiringMe>("/me"),
  createProcess: (body: { title: string; ad_titles: string[]; intake_since: string }) =>
    post<OwnHiringProcess>("/process", body),
  process: () => get<OwnHiringProcess>("/process"),
  saveProcess: async (body: {
    title: string;
    ad_titles: string[];
    assistant_user_id: number | null;
    settings: OwnHiringSettings;
  }) => (await api.put<OwnHiringProcess>(`${BASE}/process`, body)).data,
  assistantOptions: () => get<{ id: number; name: string }[]>("/assistant-options"),
  board: () => get<OwnHiringBoard>("/board"),
  newList: (bucket: OwnHiringBucket) => get<OwnHiringCard[]>(`/new?bucket=${bucket}`),
  invitationPreview: () => get<InvitationPreview>("/invitation-preview"),
  invite: (ids: number[]) => post<{ results: InviteResult[] }>("/applications/invite", { ids }),
  reject: (ids: number[]) => post<{ rejected: number }>("/applications/reject", { ids }),
  handOff: (ids: number[]) => post<{ handed_off: number }>("/applications/hand-off", { ids }),
  detail: (id: number) => get<OwnHiringDetail>(`/applications/${id}`),
  move: (id: number, stage: OwnHiringStage) =>
    post<OwnHiringDetail>(`/applications/${id}/move`, { stage }),
  teamsOutcome: (
    id: number,
    body: {
      availability: string | null;
      expected_money: string | null;
      tech_level: string | null;
      note: string | null;
      decision: "office" | "reject";
      office_start: string | null;
    },
  ) => post<OwnHiringDetail>(`/applications/${id}/teams-outcome`, body),
  noShow: (id: number) => post<OwnHiringDetail>(`/applications/${id}/no-show`),
  officeOutcome: (
    id: number,
    body: {
      note: string | null;
      decision: "contract" | "withdraw";
      contract_kind: string | null;
    },
  ) => post<OwnHiringDetail>(`/applications/${id}/office-outcome`, body),
  contractOutcome: (id: number, decision: "signed" | "withdrawn") =>
    post<OwnHiringDetail>(`/applications/${id}/contract-outcome`, { decision }),
  slots: (kind: "teams" | "office") => get<OwnHiringSlots>(`/slots?kind=${kind}`),
  queue: () => get<QueueItem[]>("/queue"),
  queueBook: (id: number, start: string) => post<{ ok: boolean }>(`/queue/${id}/book`, { start }),
  queueResult: (
    id: number,
    body: { result: "no_answer" | "callback" | "withdrawn"; callback_at: string | null },
  ) => post<{ ok: boolean }>(`/queue/${id}/result`, body),
};

/** Menu pyta o członkostwo: awaria odczytu = pozycja ukryta, serwer i tak broni tras. */
export function useOwnHiringMembership(user: unknown): boolean {
  const { data } = useQuery({
    queryKey: ownHiringKeys.me,
    queryFn: ownHiringApi.me,
    enabled: Boolean(user),
    staleTime: 5 * 60 * 1000,
  });
  return Boolean(data?.role || data?.can_create);
}
