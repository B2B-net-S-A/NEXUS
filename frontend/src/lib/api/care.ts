// „Ludzie w NEXUSIE” (16.10.2026) — opieka nad konsultantami i mapa technologii.
//
// Lustro `backend/app/api/contract_care.py` (prefiks `/api/care`). Zakres
// klientów Delivery Leada i prawo zapisu liczy serwer (`can_edit`,
// `can_curate`); front pokazuje to, co dostał. Bez stawek i danych o zdrowiu.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type CareChannel = "phone" | "meeting" | "chat";
export type PlanKind = "day_7" | "day_30" | "day_90" | "quarterly" | "pre_end";
export type PlanStatus = "open" | "done" | "skipped";
export type CardStatus = "ok" | "odmowa" | "brak_czasu" | "niechetny";
export type HiringSource = "widzial" | "slyszal" | "plotka";
export type RedeployReason = "project_end" | "wants_change" | "attrition_risk";
export type RedeployStatus = "open" | "in_progress" | "done" | "dismissed";
export type InitiativeKind = "migracja" | "nowy_system" | "ai" | "regulacje" | "inne";
export type InitiativePriority = "wysoki" | "normalny";

export interface PersonRef {
  id: number;
  name: string;
}

export interface CarePlanItem {
  id: number;
  kind: PlanKind;
  label: string;
  due_on: string;
  status: PlanStatus;
  overdue: boolean;
  done_conversation_id: number | null;
  resolved_at: string | null;
}

export interface CareConversation {
  id: number;
  occurred_on: string;
  channel: CareChannel;
  satisfaction: number | null;
  note: string | null;
  attrition_risk: boolean;
  wants_change: boolean;
  project_end_on: string | null;
  client_hiring: boolean;
  client_hiring_note: string | null;
  follow_up_on: string | null;
  author: PersonRef | null;
}

export interface Initiative {
  name: string;
  kind: InitiativeKind;
  priority: InitiativePriority;
}

export interface TechCard {
  id: number;
  contract_id: number | null;
  client_id: number;
  interview_on: string;
  status: CardStatus | null;
  is_draft: boolean;
  finalized_at: string | null;
  satisfaction: number | null;
  area: { id: number; name: string } | null;
  skills: { id: number; name: string }[];
  unrecognized_skills: string[];
  vendors: { id: number; name: string }[];
  hiring: boolean | null;
  hiring_source: HiringSource | null;
  hiring_roles: string[];
  project_end_on: string | null;
  project_end_unknown: boolean;
  team_size: string | null;
  team_externals: number | null;
  initiatives: Initiative[];
  memorable_quote: string | null;
  note: string | null;
  sales_status: "converted" | "archived" | null;
  author: PersonRef | null;
}

export interface RedeployItem {
  id: number;
  contract_id: number;
  reason: RedeployReason;
  status: RedeployStatus;
  due_on: string | null;
  source: "tech_card" | "conversation" | "manual";
  note: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface NextContact {
  due_on: string;
  label: string;
  overdue: boolean;
  plan_item_id?: number | null;
}

export interface ContractCare {
  contract: {
    id: number;
    label: string;
    candidate_id: number | null;
    candidate_name: string | null;
    client_id: number;
    client_name: string;
    job_id: number | null;
    job_title: string | null;
    status: string;
    is_live: boolean;
    start_date: string | null;
    end_date: string | null;
    day_of_cooperation: number | null;
  };
  owner: {
    user: PersonRef | null;
    source: "contract" | "client" | "delivery_lead" | null;
    explicit: boolean;
  };
  client_default_owner: PersonRef | null;
  plan: CarePlanItem[];
  next_contact: NextContact | null;
  last_satisfaction: { value: number; on: string } | null;
  conversations: CareConversation[];
  tech_cards: TechCard[];
  redeploy: RedeployItem[];
  project_end: { end_on: string | null; source: string; known_on: string } | null;
  can_edit: boolean;
}

export interface ConversationPayload {
  occurred_on: string;
  channel: CareChannel;
  satisfaction?: number | null;
  note?: string | null;
  attrition_risk?: boolean;
  wants_change?: boolean;
  project_end_on?: string | null;
  client_hiring?: boolean;
  client_hiring_note?: string | null;
  follow_up_on?: string | null;
  plan_item_id?: number | null;
}

export interface TechCardPayload {
  interview_on: string;
  finalize: boolean;
  status: CardStatus | null;
  satisfaction: number | null;
  client_area_id: number | null;
  new_area_name: string | null;
  skill_ids: number[];
  skill_names: string[];
  vendor_ids: number[];
  new_vendor_names: string[];
  hiring: boolean | null;
  hiring_source: HiringSource | null;
  hiring_roles: string[];
  project_end_on: string | null;
  project_end_unknown: boolean;
  team_size: string | null;
  team_externals: number | null;
  initiatives: Initiative[];
  memorable_quote: string | null;
  note: string | null;
}

export type TechSource = "cards" | "jobs" | "consultants" | "notes";

export interface MapTechnology {
  skill_id: number;
  name: string;
  category: string | null;
  counts: Record<TechSource, number>;
  source_count: number;
  must_jobs: number;
  consultant_months: number;
  areas: string[];
  last_seen: string | null;
  stale: boolean;
}

export interface HiringSignal {
  kind: "tech_card" | "conversation";
  id: number;
  contract_id: number | null;
  on: string;
  roles: string[];
  source: HiringSource | null;
  area: string | null;
  note: string | null;
  sales_status: "converted" | "archived" | null;
}

export interface ClientTechMap {
  client_id: number;
  client_name: string;
  technologies: MapTechnology[];
  areas: { id: number; name: string; cards: number }[];
  vendors: { id: number; name: string; cards: number }[];
  signals: HiringSignal[];
  open_jobs: { id: number; title: string; opened_on: string | null }[];
  open_jobs_count: number;
  consultants_count: number;
  cards_count: number;
  notes: { id: number; content: string; created_on: string | null }[];
  notes_count: number;
  redeploy_active: number;
  default_owner: PersonRef | null;
  can_edit: boolean;
}

export interface MyConsultantRow {
  contract_id: number;
  candidate_id: number | null;
  candidate_name: string | null;
  client_id: number;
  client_name: string;
  job_title: string | null;
  start_date: string | null;
  end_date: string | null;
  owner: PersonRef | null;
  next_contact: NextContact | null;
  overdue_count: number;
  last_conversation_on: string | null;
  last_satisfaction: number | null;
  redeploy_reasons: RedeployReason[];
}

export interface RedeployRow extends RedeployItem {
  candidate_id: number | null;
  candidate_name: string | null;
  client_id: number;
  client_name: string;
  job_title: string | null;
  end_date: string | null;
  owner: PersonRef | null;
}

export interface SkillReviewRow {
  id: number;
  name: string;
  status: "open" | "mapped" | "created" | "dismissed";
  occurrences: number;
  skill: { id: number; name: string } | null;
  reported_by: PersonRef | null;
  created_at: string;
  resolved_at: string | null;
}

export interface CareSummary {
  redeploy_active: number;
  skill_review_open: number;
  can_edit: boolean;
  can_curate: boolean;
}

export const CHANNEL_LABELS: Record<CareChannel, string> = {
  phone: "Telefon",
  meeting: "Spotkanie",
  chat: "Czat",
};

export const CARD_STATUS_LABELS: Record<CardStatus, string> = {
  ok: "Rozmowa odbyta",
  odmowa: "Odmowa",
  brak_czasu: "Brak czasu",
  niechetny: "Niechętny",
};

export const HIRING_SOURCE_LABELS: Record<HiringSource, string> = {
  widzial: "widział",
  slyszal: "słyszał",
  plotka: "plotka",
};

export const REDEPLOY_REASON_LABELS: Record<RedeployReason, string> = {
  project_end: "Koniec projektu",
  wants_change: "Chce zmiany projektu",
  attrition_risk: "Ryzyko odejścia",
};

export const REDEPLOY_STATUS_LABELS: Record<RedeployStatus, string> = {
  open: "Nowe",
  in_progress: "W toku",
  done: "Przepięty",
  dismissed: "Nie dotyczy",
};

export const INITIATIVE_KIND_LABELS: Record<InitiativeKind, string> = {
  migracja: "Migracja",
  nowy_system: "Nowy system",
  ai: "AI",
  regulacje: "Regulacje",
  inne: "Inne",
};

export const SOURCE_LABELS: Record<TechSource, string> = {
  cards: "Rozmowy (karty technologiczne)",
  jobs: "Rekrutacje klienta",
  consultants: "Nasi konsultanci",
  notes: "Notatki o stacku",
};

export const OWNER_SOURCE_LABELS: Record<"contract" | "client" | "delivery_lead", string> = {
  contract: "przypisany do kontraktu",
  client: "domyślny dla klienta",
  delivery_lead: "Delivery Lead kontraktu",
};

export const careKeys = {
  all: ["care"] as const,
  contract: (id: number) => ["care", "contract", id] as const,
  clientMap: (id: number) => ["care", "client", id, "tech-map"] as const,
  clientAreas: (id: number) => ["care", "client", id, "areas"] as const,
  owners: ["care", "owners"] as const,
  myConsultants: (scope: "mine" | "all") => ["care", "my-consultants", scope] as const,
  redeploy: (state: "active" | "closed") => ["care", "redeploy", state] as const,
  skillReview: (state: "open" | "closed") => ["care", "skill-review", state] as const,
  summary: ["care", "summary"] as const,
};

export function useContractCare(contractId: number, enabled = true) {
  return useQuery({
    queryKey: careKeys.contract(contractId),
    queryFn: async () =>
      (await api.get<ContractCare>(`/api/care/contracts/${contractId}`)).data,
    enabled: enabled && Number.isFinite(contractId) && contractId > 0,
  });
}

export function useClientTechMap(clientId: number, enabled = true) {
  return useQuery({
    queryKey: careKeys.clientMap(clientId),
    queryFn: async () =>
      (await api.get<ClientTechMap>(`/api/care/clients/${clientId}/tech-map`)).data,
    enabled: enabled && Number.isFinite(clientId) && clientId > 0,
  });
}

export function useClientAreas(clientId: number, enabled = true) {
  return useQuery({
    queryKey: careKeys.clientAreas(clientId),
    queryFn: async () =>
      (
        await api.get<{ items: { id: number; name: string }[] }>(
          `/api/care/clients/${clientId}/areas`,
        )
      ).data.items,
    enabled: enabled && clientId > 0,
  });
}

export function useCareOwners(enabled = true) {
  return useQuery({
    queryKey: careKeys.owners,
    queryFn: async () =>
      (await api.get<{ items: PersonRef[] }>("/api/care/owners")).data.items,
    staleTime: 5 * 60 * 1000,
    enabled,
  });
}

export function useMyConsultants(scope: "mine" | "all") {
  return useQuery({
    queryKey: careKeys.myConsultants(scope),
    queryFn: async () =>
      (
        await api.get<{ items: MyConsultantRow[]; total: number }>(
          "/api/care/my-consultants",
          { params: { scope } },
        )
      ).data,
  });
}

export function useRedeployQueue(state: "active" | "closed") {
  return useQuery({
    queryKey: careKeys.redeploy(state),
    queryFn: async () =>
      (
        await api.get<{ items: RedeployRow[]; total: number; can_edit: boolean }>(
          "/api/care/redeploy",
          { params: { state } },
        )
      ).data,
  });
}

export function useSkillReview(state: "open" | "closed", enabled = true) {
  return useQuery({
    queryKey: careKeys.skillReview(state),
    queryFn: async () =>
      (
        await api.get<{ items: SkillReviewRow[]; can_curate: boolean }>(
          "/api/care/skill-review",
          { params: { state } },
        )
      ).data,
    enabled,
  });
}

export function useCareSummary() {
  return useQuery({
    queryKey: careKeys.summary,
    queryFn: async () => (await api.get<CareSummary>("/api/care/summary")).data,
  });
}

export async function searchVendors(q: string) {
  return (
    await api.get<{ items: { id: number; name: string }[] }>("/api/care/vendors", {
      params: { q },
    })
  ).data.items;
}

export async function searchSkills(q: string) {
  return (
    await api.get<{ items: { id: number; name: string; category: string | null }[] }>(
      "/api/skills/autocomplete",
      { params: { q, limit: 12 } },
    )
  ).data.items;
}

function useContractMutation<TVars>(
  contractId: number,
  request: (vars: TVars) => Promise<ContractCare>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: (data) => {
      queryClient.setQueryData(careKeys.contract(contractId), data);
      queryClient.invalidateQueries({ queryKey: ["care", "client", data.contract.client_id] });
      queryClient.invalidateQueries({ queryKey: ["care", "my-consultants"] });
      queryClient.invalidateQueries({ queryKey: ["care", "redeploy"] });
      queryClient.invalidateQueries({ queryKey: careKeys.summary });
    },
  });
}

export function useSetContractOwner(contractId: number) {
  return useContractMutation(contractId, async (userId: number | null) =>
    (
      await api.put<ContractCare>(`/api/care/contracts/${contractId}/owner`, {
        user_id: userId,
      })
    ).data,
  );
}

export function useAddConversation(contractId: number) {
  return useContractMutation(contractId, async (payload: ConversationPayload) =>
    (
      await api.post<ContractCare>(
        `/api/care/contracts/${contractId}/conversations`,
        payload,
      )
    ).data,
  );
}

export function useUpdatePlanItem(contractId: number) {
  return useContractMutation(
    contractId,
    async ({ itemId, status }: { itemId: number; status: "open" | "skipped" }) =>
      (await api.patch<ContractCare>(`/api/care/plan-items/${itemId}`, { status })).data,
  );
}

export function useSaveTechCard(contractId: number) {
  return useContractMutation(
    contractId,
    async ({ cardId, payload }: { cardId: number | null; payload: TechCardPayload }) =>
      cardId == null
        ? (
            await api.post<ContractCare>(
              `/api/care/contracts/${contractId}/tech-cards`,
              payload,
            )
          ).data
        : (await api.put<ContractCare>(`/api/care/tech-cards/${cardId}`, payload)).data,
  );
}

export function useAddStackNote(clientId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (content: string) =>
      (await api.post(`/api/care/clients/${clientId}/stack-notes`, { content })).data,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: careKeys.clientMap(clientId) }),
  });
}

export function useSetClientDefaultOwner(clientId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (userId: number | null) =>
      (
        await api.put(`/api/care/clients/${clientId}/default-owner`, {
          user_id: userId,
        })
      ).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: careKeys.all }),
  });
}

export function useUpdateRedeploy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      itemId,
      status,
      note,
    }: {
      itemId: number;
      status?: RedeployStatus;
      note?: string | null;
    }) =>
      (
        await api.patch<RedeployItem>(`/api/care/redeploy/${itemId}`, {
          ...(status ? { status } : {}),
          ...(note !== undefined ? { note } : {}),
        })
      ).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: careKeys.all }),
  });
}

export function useResolveSkillReview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (
      action:
        | { kind: "map"; itemId: number; skillId: number }
        | { kind: "create"; itemId: number; canonicalName: string; category: string | null }
        | { kind: "dismiss"; itemId: number },
    ) => {
      const base = `/api/care/skill-review/${action.itemId}`;
      if (action.kind === "map") {
        return (await api.post(`${base}/map`, { skill_id: action.skillId })).data;
      }
      if (action.kind === "create") {
        return (
          await api.post(`${base}/create`, {
            canonical_name: action.canonicalName,
            category: action.category,
          })
        ).data;
      }
      return (await api.post(`${base}/dismiss`)).data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: careKeys.all }),
  });
}

/** Ostatni dzień miesiąca `YYYY-MM` (koniec projektu podaje się miesiącem). */
export function monthEnd(month: string): string | null {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (!match) return null;
  const year = Number(match[1]);
  const monthIndex = Number(match[2]);
  if (monthIndex < 1 || monthIndex > 12) return null;
  const last = new Date(Date.UTC(year, monthIndex, 0)).getUTCDate();
  return `${match[1]}-${match[2]}-${String(last).padStart(2, "0")}`;
}

/** `YYYY-MM` z daty ISO (do pola miesiąca końca projektu). */
export function monthOf(date: string | null | undefined): string {
  return date ? date.slice(0, 7) : "";
}
