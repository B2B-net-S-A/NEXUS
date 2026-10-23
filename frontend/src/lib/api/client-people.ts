// „Ludzie w NEXUSIE”, etap 2 (17.10.2026) — struktura u klienta i opinie klienta.
//
// Lustro tras `backend/app/api/contract_care.py` (prefiks `/api/care`):
// `GET /clients/{id}/org`, `PATCH /clients/{id}/contacts/{contact_id}`,
// `POST /clients/{id}/feedback`, `GET /contracts/{id}/feedback`,
// `GET /feedback-requests`. Kto widzi (D11) i kto zapisuje liczy serwer
// (`can_edit_org`, `can_write_feedback`); front pokazuje to, co dostał.
// Bez stawek i danych o zdrowiu.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { hasRole, type User } from "@/store/auth";

import { careKeys, type PersonRef } from "./care";

export type FeedbackChannel = "phone" | "meeting" | "teams" | "email";
export type ExtensionOutlook = "yes" | "likely" | "unsure" | "no";
export type FeedbackReason = "pre_end" | "quarterly";
export type ScoreField = "quality" | "communication" | "autonomy";

export interface LastFeedback {
  session_id: number;
  held_on: string;
  average: number | null;
}

export interface OrgConsultant {
  contract_id: number;
  candidate_id: number | null;
  candidate_name: string | null;
  role: string | null;
  end_date: string | null;
  end_source: "order" | "contract" | null;
  last_feedback: LastFeedback | null;
}

export interface FeedbackRequestBrief {
  reasons: FeedbackReason[];
  due_on: string;
  overdue: boolean;
}

export interface OrgPerson {
  id: number;
  name: string;
  position: string | null;
  department_text: string | null;
  area_id: number | null;
  depth: number;
  is_decision_maker: boolean;
  is_hiring_manager: boolean;
  is_manager: boolean;
  reports_to: PersonRef | null;
  subordinates: PersonRef[];
  email: string | null;
  phone: string | null;
  hiring_manager_jobs: { id: number; title: string; status: string }[];
  hiring_manager_jobs_total: number;
  consultants: OrgConsultant[];
  last_feedback: LastFeedback | null;
  feedback_request: FeedbackRequestBrief | null;
  department_hint: { area_id: number | null; name: string } | null;
}

export interface OrgDepartment {
  area: { id: number; name: string } | null;
  people: OrgPerson[];
}

export interface ManagerHint {
  contact_id: number;
  name: string;
  position: string | null;
  source: "line_manager" | "client_pm_name";
  text: string;
}

export interface WithoutManagerRow extends OrgConsultant {
  line_manager: string | null;
  client_pm_name: string | null;
  manager_outside_client: boolean;
  hint: ManagerHint | null;
}

export interface FeedbackRequest {
  contact_id: number;
  contact_name: string;
  position: string | null;
  client_id: number;
  client_name: string;
  reasons: FeedbackReason[];
  due_on: string;
  overdue: boolean;
  last_feedback: LastFeedback | null;
  consultants: OrgConsultant[];
  owner_ids: number[];
}

export interface ClientOrg {
  client_id: number;
  client_name: string;
  areas: { id: number; name: string }[];
  departments: OrgDepartment[];
  without_manager: WithoutManagerRow[];
  requests: FeedbackRequest[];
  people_count: number;
  consultants_count: number;
  can_edit_org: boolean;
  can_write_feedback: boolean;
}

export interface ContactOrgPayload {
  reports_to_contact_id?: number | null;
  client_area_id?: number | null;
  new_area_name?: string | null;
}

export interface FeedbackScorePayload {
  contract_id: number;
  quality?: number | null;
  communication?: number | null;
  autonomy?: number | null;
}

export interface FeedbackPayload {
  contact_id: number;
  held_on: string;
  channel: FeedbackChannel;
  extension_outlook: ExtensionOutlook | null;
  note: string | null;
  scores: FeedbackScorePayload[];
}

export interface ContractFeedbackItem {
  session_id: number;
  held_on: string;
  channel: FeedbackChannel;
  contact: PersonRef | null;
  quality: number | null;
  communication: number | null;
  autonomy: number | null;
  average: number | null;
  extension_outlook: ExtensionOutlook | null;
  note: string | null;
  author: PersonRef | null;
}

export const FEEDBACK_CHANNEL_LABELS: Record<FeedbackChannel, string> = {
  phone: "Telefon",
  meeting: "Spotkanie",
  teams: "Teams",
  email: "E-mail",
};

export const EXTENSION_LABELS: Record<ExtensionOutlook, string> = {
  yes: "tak",
  likely: "raczej tak",
  unsure: "nie wiem",
  no: "nie",
};

export const SCORE_LABELS: Record<ScoreField, string> = {
  quality: "Jakość pracy",
  communication: "Komunikacja",
  autonomy: "Samodzielność",
};

export const REASON_LABELS: Record<FeedbackReason, string> = {
  pre_end: "przed końcem zamówienia",
  quarterly: "kwartał bez opinii",
};

export const FEEDBACK_NOTE_MAX = 2000;

/**
 * D11: strukturę u klienta i opinie widzą opiekun (DL, TCM, admin) i Head of
 * Recruitment. Lustro `_PEOPLE_READER_ROLES` — serwer i tak odmawia (403).
 */
export function canReadClientPeople(user: User | null | undefined): boolean {
  return hasRole(
    user,
    "admin",
    "delivery_lead",
    "talent_community_manager",
    "head_of_recruitment",
  );
}

export const clientPeopleKeys = {
  org: (clientId: number) => ["care", "client", clientId, "org"] as const,
  contractFeedback: (contractId: number) =>
    ["care", "contract", contractId, "feedback"] as const,
  requests: (scope: "mine" | "all") => ["care", "feedback-requests", scope] as const,
};

export function useClientOrg(clientId: number, enabled = true) {
  return useQuery({
    queryKey: clientPeopleKeys.org(clientId),
    queryFn: async () =>
      (await api.get<ClientOrg>(`/api/care/clients/${clientId}/org`)).data,
    enabled: enabled && Number.isFinite(clientId) && clientId > 0,
  });
}

export function useContractFeedback(contractId: number, enabled = true) {
  return useQuery({
    queryKey: clientPeopleKeys.contractFeedback(contractId),
    queryFn: async () =>
      (
        await api.get<{
          items: ContractFeedbackItem[];
          client_id: number;
          can_write: boolean;
        }>(`/api/care/contracts/${contractId}/feedback`)
      ).data,
    enabled: enabled && Number.isFinite(contractId) && contractId > 0,
  });
}

export function useFeedbackRequests(scope: "mine" | "all", enabled = true) {
  return useQuery({
    queryKey: clientPeopleKeys.requests(scope),
    queryFn: async () =>
      (
        await api.get<{ items: FeedbackRequest[]; total: number }>(
          "/api/care/feedback-requests",
          { params: { scope } },
        )
      ).data,
    enabled,
  });
}

export function useUpdateContactOrg(clientId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      contactId,
      payload,
    }: {
      contactId: number;
      payload: ContactOrgPayload;
    }) =>
      (
        await api.patch<ClientOrg>(
          `/api/care/clients/${clientId}/contacts/${contactId}`,
          payload,
        )
      ).data,
    onSuccess: (org) => {
      // Drzewo wraca w odpowiedzi — bez drugiego zapytania. Nowy dział zasila
      // też mapę technologii i listę obszarów kart.
      queryClient.setQueryData(clientPeopleKeys.org(clientId), org);
      void queryClient.invalidateQueries({ queryKey: careKeys.clientMap(clientId) });
      void queryClient.invalidateQueries({ queryKey: careKeys.clientAreas(clientId) });
    },
  });
}

export function useSaveClientFeedback(clientId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: FeedbackPayload) =>
      (
        await api.post<{ id: number; contract_ids: number[] }>(
          `/api/care/clients/${clientId}/feedback`,
          payload,
        )
      ).data,
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: clientPeopleKeys.org(clientId) });
      void queryClient.invalidateQueries({ queryKey: ["care", "feedback-requests"] });
      // Tablica opieki, karta konsultanta i sprawy (22.10.2026).
      void queryClient.invalidateQueries({ queryKey: ["care", "board"] });
      void queryClient.invalidateQueries({ queryKey: ["care", "contract"] });
      void queryClient.invalidateQueries({ queryKey: ["admin-cases"] });
      // „Klienci”: ostatnia opinia i „czeka na opinię” (audyt 22.10, F91).
      void queryClient.invalidateQueries({ queryKey: ["care", "clients"] });
      void queryClient.invalidateQueries({ queryKey: careKeys.summary });
      for (const contractId of saved.contract_ids) {
        void queryClient.invalidateQueries({
          queryKey: clientPeopleKeys.contractFeedback(contractId),
        });
      }
    },
  });
}

/** Wiersz oceny bez żadnej oceny to „pomiń” — nie idzie do serwera. */
export function scoresForPayload(
  scores: Record<number, Partial<Record<ScoreField, number | null>>>,
  skipped: ReadonlySet<number>,
): FeedbackScorePayload[] {
  return Object.entries(scores)
    .map(([contractId, values]) => ({
      contract_id: Number(contractId),
      quality: values.quality ?? null,
      communication: values.communication ?? null,
      autonomy: values.autonomy ?? null,
    }))
    .filter(
      (row) =>
        !skipped.has(row.contract_id) &&
        (row.quality !== null || row.communication !== null || row.autonomy !== null),
    );
}

/** „4,3 / 5” — średnia opinii po polsku. */
export function formatAverage(value: number | null | undefined): string {
  if (value === null || value === undefined) return "bez ocen";
  return `${value.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} / 5`;
}
