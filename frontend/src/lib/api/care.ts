// „Ludzie w NEXUSIE” (16.10.2026) — opieka nad konsultantami i mapa technologii.
//
// Lustro `backend/app/api/contract_care.py` i `care_consultants.py` (prefiks
// `/api/care`). Zakres klientów Delivery Leada i prawo zapisu liczy serwer
// (`can_edit`, `can_curate`, `can_change_cadence`, `can_assign`); front
// pokazuje to, co dostał. Bez stawek i danych o zdrowiu.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

import type { FeedbackReason, LastFeedback, OrgConsultant } from "./client-people";

export type CareChannel = "phone" | "meeting" | "chat";
/** `day_7` i `pre_end` — kamienie; `cadence` — rozmowa z rytmu; reszta to stały plan sprzed 17.10.2026. */
export type PlanKind = "day_7" | "cadence" | "pre_end" | "day_30" | "day_90" | "quarterly";
/** Rytm kontaktu (etap 3, O7). */
export type CadenceLevel = "biweekly" | "monthly" | "quarterly" | "milestones" | "paused";
export type CadenceReason =
  | "new_at_client"
  | "weak_feedback"
  | "order_end"
  | "wants_change"
  | "stable"
  | "person_request"
  | "long_absence"
  | "other"
  | "imported";
export type SkipReason =
  | "recent_contact"
  | "unreachable"
  | "absence"
  | "person_request"
  | "ending"
  | "other";
export type OwnerReason =
  | "new_consultants"
  | "balance_load"
  | "owner_leaving"
  | "client_change"
  | "person_request"
  | "other";
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
  skip_reason?: SkipReason | null;
  skip_note?: string | null;
}

/** Obecny rytm: poziom, skąd (program 90 dni, domyślny, zmiana), do kiedy i powód. */
export interface CadenceCurrent {
  level: CadenceLevel;
  source: "program" | "default" | "period";
  starts_on: string | null;
  until_on: string | null;
  /** Rytm po dacie „do kiedy” (albo po programie pierwszych 90 dni). */
  returns_to: CadenceLevel | null;
  reason: CadenceReason | null;
  note: string | null;
  author: PersonRef | null;
}

export type CadenceSignal =
  | { kind: "weak_feedback"; average: number; on: string }
  | { kind: "order_end"; days: number; on: string }
  | { kind: "project_end"; on: string | null }
  | { kind: "wants_change" }
  | { kind: "attrition_risk" }
  | { kind: "overdue"; days: number };

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
  cadence?: (CadenceCurrent & { can_edit: boolean }) | null;
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

/** Technologia w wierszu działu (D16) — źródła tylko z tego działu. */
export interface DepartmentTechnology {
  skill_id: number;
  name: string;
  counts: Record<TechSource, number>;
  source_count: number;
  last_seen: string | null;
  stale: boolean;
}

export interface MapDepartment {
  area: { id: number; name: string };
  technologies: DepartmentTechnology[];
  technologies_total: number;
  /** Osoby z działu z naszymi konsultantami pod sobą (najwięcej pierwsza). */
  managers: { id: number; name: string; position: string | null; consultants: number }[];
  consultants: number;
  last_seen: string | null;
  has_fresh_source: boolean;
  /** „W bazie”: osoby z tymi umiejętnościami naraz; `count` null = nie policzono. */
  base: { skills: string[]; count: number | null };
}

/** „Luki do dopytania” (D16) — te same pytania idą do okna rozmowy opieki. */
export type TechGap =
  | {
      kind: "area_no_source";
      area: { id: number; name: string };
      last_seen: string | null;
    }
  | {
      kind: "manager_unplaced";
      contact: PersonRef;
      position: string | null;
      area: { id: number; name: string } | null;
      consultants: number;
    }
  | {
      kind: "single_source";
      skill_id: number;
      name: string;
      source: TechSource;
      refs: number;
      last_seen: string | null;
      areas: string[];
    };

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
  departments: MapDepartment[];
  gaps: TechGap[];
  default_owner: PersonRef | null;
  can_edit: boolean;
}

/** Wiersz „Konsultanci” (M1). */
export interface ConsultantRow {
  contract_id: number;
  candidate_id: number | null;
  candidate_name: string | null;
  client_id: number;
  client_name: string;
  job_title: string | null;
  contract_type: "b2b" | "uop" | "uzlecenie" | null;
  start_date: string | null;
  end_date: string | null;
  owner: PersonRef | null;
  is_mine: boolean;
  manager: ClientManagerRef | null;
  cadence: CadenceCurrent;
  next_contact: (NextContact & { kind: WeekReasonKind; overdue_days: number }) | null;
  last_conversation: {
    id: number;
    occurred_on: string;
    satisfaction: number | null;
    note_excerpt: string | null;
    signals: string[];
  } | null;
  signals: CadenceSignal[];
  suggested_level: CadenceLevel | null;
  conversations: { this_month: number; next_month: number };
  can_change_cadence: boolean;
}

export interface CareConsultants {
  today: string;
  months: { this: { from: string; to: string }; next: { from: string; to: string } };
  items: ConsultantRow[];
  total: number;
  feedback_visible: boolean;
}

export interface CadenceHistoryStep {
  on: string;
  kind: "start" | "program_end" | "change" | "return";
  level: CadenceLevel;
  reason: CadenceReason | null;
  note: string | null;
  until_on: string | null;
  author: PersonRef | null;
  future: boolean;
}

export interface CadenceUpcoming {
  due_on: string;
  kind: PlanKind;
  label: string;
}

/** Okno „Rytm kontaktu” (M2); `preview` tylko przy podglądzie zmiany. */
export interface ContractCadence {
  contract_id: number;
  candidate_name: string | null;
  client_name: string;
  start_date: string | null;
  end_date: string | null;
  is_live: boolean;
  owner: PersonRef | null;
  manager: ClientManagerRef | null;
  current: CadenceCurrent;
  history: CadenceHistoryStep[];
  upcoming: CadenceUpcoming[];
  signals: CadenceSignal[];
  suggested_level: CadenceLevel | null;
  preview: {
    level: CadenceLevel;
    until_on: string | null;
    returns_to: CadenceLevel | null;
    upcoming: CadenceUpcoming[];
    owner_month: { owner: PersonRef; month: string; before: number; after: number } | null;
  } | null;
  can_edit: boolean;
}

export interface CadencePayload {
  level: CadenceLevel;
  reason: Exclude<CadenceReason, "imported">;
  note: string | null;
  until_on: string | null;
}

/** „Przydział” (M3): opiekunowie z obciążeniem z rytmów i kontrakty z podpowiedzią. */
export interface OwnerLoad {
  id: number;
  name: string;
  is_delivery_lead: boolean;
  consultants: number;
  conversations: number;
  by_level: Partial<Record<CadenceLevel, number>>;
  clients: string[];
  over_threshold: boolean;
}

export type OwnerHint = "contract" | "client" | "delivery_lead" | "default_inactive" | "no_default";

export interface AssignmentRow {
  contract_id: number;
  candidate_id: number | null;
  candidate_name: string | null;
  job_title: string | null;
  contract_type: "b2b" | "uop" | "uzlecenie" | null;
  client_id: number;
  client_name: string;
  start_date: string | null;
  end_date: string | null;
  owner: PersonRef | null;
  owner_source: "contract" | "client" | "delivery_lead" | null;
  explicit_owner_id: number | null;
  client_default_owner: PersonRef | null;
  hint: OwnerHint;
  ending_soon: boolean;
  cadence_level: CadenceLevel | null;
  conversations_next_month: number;
}

export interface CareAssignment {
  today: string;
  month: { from: string; to: string };
  counts: {
    active: number;
    without_owner: number;
    owners: number;
    conversations: number;
    ending: number;
  };
  threshold: { monthly_conversations: number | null };
  owners: OwnerLoad[];
  items: AssignmentRow[];
  clients: {
    id: number;
    name: string;
    default_owner: PersonRef | null;
    default_owner_active: boolean;
    consultants: number;
  }[];
  owner_choices: PersonRef[];
  can_assign: boolean;
  can_edit_threshold: boolean;
  can_edit_defaults: boolean;
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

// ── „Ten tydzień”, oś konsultanta, „Przekaż do front office” (D15) ────────

export type WeekReasonKind = PlanKind | "follow_up";
export type FrontOfficeReason = "project_end" | "wants_change";

export interface WeekReason {
  kind: WeekReasonKind;
  label: string;
  due_on: string;
  overdue: boolean;
  plan_item_id: number | null;
  from_conversation_on: string | null;
}

export interface ClientManagerRef {
  id: number;
  name: string;
  position: string | null;
  area: { id: number; name: string } | null;
}

export interface WeekContact {
  contract_id: number;
  candidate_id: number | null;
  candidate_name: string | null;
  client_id: number;
  client_name: string;
  job_title: string | null;
  start_date: string | null;
  end_date: string | null;
  owner: PersonRef | null;
  reasons: WeekReason[];
  due_on: string;
  overdue: boolean;
  overdue_days: number;
  plan_item_id: number | null;
  manager: ClientManagerRef | null;
  last_conversation: {
    id: number;
    occurred_on: string;
    satisfaction: number | null;
    note_excerpt: string | null;
    signals: string[];
  } | null;
  signals: RedeployReason[];
  front_office: { reasons: FrontOfficeReason[]; handed_off_on: string | null };
}

export interface WeekFeedback {
  contact_id: number;
  contact_name: string;
  position: string | null;
  client_id: number;
  client_name: string;
  area: { id: number; name: string } | null;
  reasons: FeedbackReason[];
  due_on: string;
  overdue: boolean;
  last_feedback: LastFeedback | null;
  consultants: OrgConsultant[];
}

export interface CareWeek {
  week: { from: string; to: string; today: string; is_current: boolean };
  scope: "mine" | "all";
  contacts: WeekContact[];
  feedback: WeekFeedback[];
  feedback_visible: boolean;
  counts: { contacts: number; overdue: number; feedback: number; front_office: number };
  can_edit: boolean;
  can_write_feedback: boolean;
}

export type TimelineKind =
  | "recruitment"
  | "start"
  | "order_start"
  | "conversation"
  | "tech_card"
  | "feedback"
  | "redeploy"
  | "owner"
  | "cadence"
  | "cadence_return"
  | "handoff"
  | "plan"
  | "order_end"
  | "contract_end";

export interface TimelineEvent {
  kind: TimelineKind;
  on: string;
  title: string;
  detail: string | null;
  link: string | null;
  future: boolean;
}

export interface ContractTimeline {
  contract: {
    id: number;
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
  };
  owner: PersonRef | null;
  manager: ClientManagerRef | null;
  signals: RedeployReason[];
  front_office_reasons: FrontOfficeReason[];
  events: TimelineEvent[];
  feedback_visible: boolean;
  can_edit: boolean;
}

export interface FrontOfficeJob {
  job_id: number;
  title: string;
  client_name: string | null;
  client_reference: string | null;
  score: number;
  matching_must: string[];
  gap_must: string[];
}

export interface FrontOfficeOverview {
  contract_id: number;
  eligible: boolean;
  reasons: FrontOfficeReason[];
  end_date: string | null;
  /** `unavailable` = wyszukiwanie nie zadziałało — to nie „nic nie pasuje”. */
  status: "ok" | "unavailable";
  jobs: FrontOfficeJob[];
  handoffs: { on: string; by: PersonRef | null; job_ids: number[]; notified_count: number }[];
  can_edit: boolean;
}

export interface HandoffResult {
  contract_id: number;
  handed_off_on: string;
  reasons: FrontOfficeReason[];
  job_ids: number[];
  recipients: PersonRef[];
  notified: PersonRef[];
  redeploy_item_id: number | null;
}

export const FRONT_OFFICE_REASON_LABELS: Record<FrontOfficeReason, string> = {
  project_end: "kończy projekt",
  wants_change: "chce zmiany projektu",
};

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

/** Poziomy rytmu w kolejności od najczęstszego (okno „Rytm kontaktu”). */
export const CADENCE_LEVELS: CadenceLevel[] = [
  "biweekly",
  "monthly",
  "quarterly",
  "milestones",
  "paused",
];

export const CADENCE_LEVEL_LABELS: Record<CadenceLevel, string> = {
  biweekly: "co 2 tygodnie",
  monthly: "co miesiąc",
  quarterly: "co kwartał",
  milestones: "tylko kamienie",
  paused: "wstrzymany",
};

/** Kiedy który rytm (podpis w oknie zmiany). */
export const CADENCE_LEVEL_HINTS: Record<CadenceLevel, string> = {
  biweekly: "nowi, sygnał, zmiana",
  monthly: "domyślnie po 90 dniach",
  quarterly: "stabilnie, długo u klienta",
  milestones: "start i koniec zamówienia",
  paused: "nieobecność, prośba osoby",
};

export const CADENCE_REASON_LABELS: Record<CadenceReason, string> = {
  new_at_client: "Nowy u klienta",
  weak_feedback: "Słaba opinia menedżera u klienta",
  order_end: "Koniec zamówienia",
  wants_change: "Chce zmiany projektu",
  stable: "Stabilnie",
  person_request: "Prośba osoby",
  long_absence: "Długa nieobecność",
  other: "Inny powód",
  imported: "Z Compassa",
};

export const SKIP_REASON_LABELS: Record<SkipReason, string> = {
  recent_contact: "Niedawno rozmawialiśmy",
  unreachable: "Konsultant nieosiągalny",
  absence: "Nieobecność konsultanta",
  person_request: "Prośba konsultanta",
  ending: "Kończy współpracę",
  other: "Inny powód",
};

export const OWNER_REASON_LABELS: Record<OwnerReason, string> = {
  new_consultants: "Nowi konsultanci klienta",
  balance_load: "Wyrównanie obciążenia",
  owner_leaving: "Odejście albo nieobecność opiekuna",
  client_change: "Zmiana u klienta",
  person_request: "Prośba konsultanta",
  other: "Inny powód",
};

export const careKeys = {
  all: ["care"] as const,
  contract: (id: number) => ["care", "contract", id] as const,
  clientMap: (id: number) => ["care", "client", id, "tech-map"] as const,
  clientAreas: (id: number) => ["care", "client", id, "areas"] as const,
  owners: ["care", "owners"] as const,
  consultants: ["care", "consultants"] as const,
  /** `level`/`until` — podgląd zmiany rytmu (null = sam odczyt). */
  cadence: (contractId: number, level: CadenceLevel | null = null, until: string | null = null) =>
    ["care", "contract", contractId, "cadence", level, until] as const,
  assignment: ["care", "assignment"] as const,
  redeploy: (state: "active" | "closed") => ["care", "redeploy", state] as const,
  skillReview: (state: "open" | "closed") => ["care", "skill-review", state] as const,
  summary: ["care", "summary"] as const,
  /** `from` = null — tydzień liczy serwer (w weekend następny). */
  week: (scope: "mine" | "all", from: string | null) => ["care", "week", scope, from] as const,
  timeline: (contractId: number) => ["care", "contract", contractId, "timeline"] as const,
  frontOffice: (contractId: number) =>
    ["care", "contract", contractId, "front-office"] as const,
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

export function useCareConsultants() {
  return useQuery({
    queryKey: careKeys.consultants,
    queryFn: async () => (await api.get<CareConsultants>("/api/care/consultants")).data,
    staleTime: 60_000,
  });
}

/** Rytm kontraktu; `level` (i `until`) = podgląd zmiany bez zapisu. */
export function useContractCadence(
  contractId: number,
  proposal: { level: CadenceLevel | null; until: string | null } = { level: null, until: null },
  enabled = true,
) {
  const params: Record<string, string> = {};
  if (proposal.level) params.level = proposal.level;
  if (proposal.level && proposal.until) params.until_on = proposal.until;
  return useQuery({
    queryKey: careKeys.cadence(contractId, proposal.level, proposal.level ? proposal.until : null),
    queryFn: async () =>
      (
        await api.get<ContractCadence>(`/api/care/contracts/${contractId}/cadence`, { params })
      ).data,
    enabled: enabled && Number.isFinite(contractId) && contractId > 0,
    // Podgląd przy zmianie poziomu nie miga pustym oknem.
    placeholderData: (previous) => previous,
  });
}

export function useCareAssignment(enabled = true) {
  return useQuery({
    queryKey: careKeys.assignment,
    queryFn: async () => (await api.get<CareAssignment>("/api/care/assignment")).data,
    enabled,
  });
}

/** Po zmianie opiekuna albo rytmu: listy, przydział, tydzień i oś. */
function invalidateCareLists(
  queryClient: ReturnType<typeof useQueryClient>,
  contractIds: number[] = [],
) {
  void queryClient.invalidateQueries({ queryKey: careKeys.consultants });
  void queryClient.invalidateQueries({ queryKey: careKeys.assignment });
  void queryClient.invalidateQueries({ queryKey: ["care", "week"] });
  for (const id of contractIds) {
    void queryClient.invalidateQueries({ queryKey: ["care", "contract", id] });
  }
}

export function useSetContractCadence(contractId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CadencePayload) =>
      (
        await api.post<ContractCadence>(`/api/care/contracts/${contractId}/cadence`, payload)
      ).data,
    onSuccess: () => invalidateCareLists(queryClient, [contractId]),
  });
}

export function useAssignOwners() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      contract_ids: number[];
      owner_user_id: number;
      reason: OwnerReason;
    }) =>
      (
        await api.post<{ changed: number; unchanged: number; owner: PersonRef }>(
          "/api/care/assignment",
          payload,
        )
      ).data,
    onSuccess: (_data, payload) => invalidateCareLists(queryClient, payload.contract_ids),
  });
}

export function useSetLoadThreshold() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (value: number | null) =>
      (
        await api.put<{ monthly_conversations: number | null }>(
          "/api/care/assignment/threshold",
          { monthly_conversations: value },
        )
      ).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: careKeys.assignment }),
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
      queryClient.invalidateQueries({ queryKey: careKeys.consultants });
      queryClient.invalidateQueries({ queryKey: careKeys.assignment });
      queryClient.invalidateQueries({ queryKey: ["care", "redeploy"] });
      queryClient.invalidateQueries({ queryKey: careKeys.summary });
      queryClient.invalidateQueries({ queryKey: ["care", "week"] });
      queryClient.invalidateQueries({ queryKey: careKeys.timeline(contractId) });
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
    async ({
      itemId,
      status,
      reason,
      note,
    }: {
      itemId: number;
      status: "open" | "skipped";
      /** Wymagany przy „Pomiń” (serwer odpowiada 422 bez powodu). */
      reason?: SkipReason;
      note?: string | null;
    }) =>
      (
        await api.patch<ContractCare>(`/api/care/plan-items/${itemId}`, {
          status,
          ...(status === "skipped" ? { reason, note: note ?? null } : {}),
        })
      ).data,
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

export function useCareWeek(scope: "mine" | "all", from: string | null) {
  return useQuery({
    queryKey: careKeys.week(scope, from),
    queryFn: async () =>
      (
        await api.get<CareWeek>("/api/care/week", {
          params: from ? { scope, from } : { scope },
        })
      ).data,
    // Ta sama lista stoi w zakładce i liczniku zaległych — bez ponownego
    // liczenia przy każdym przełączeniu zakładki (audyt wydajności 17.10).
    staleTime: 60_000,
  });
}

export function useContractTimeline(contractId: number, enabled = true) {
  return useQuery({
    queryKey: careKeys.timeline(contractId),
    queryFn: async () =>
      (await api.get<ContractTimeline>(`/api/care/contracts/${contractId}/timeline`)).data,
    enabled: enabled && Number.isFinite(contractId) && contractId > 0,
  });
}

/** Pasujące rekrutacje liczy silnik „Pasuje też do” — drogo, więc bez odświeżania w tle. */
export function useFrontOffice(contractId: number, enabled = true) {
  return useQuery({
    queryKey: careKeys.frontOffice(contractId),
    queryFn: async () =>
      (
        await api.get<FrontOfficeOverview>(
          `/api/care/contracts/${contractId}/front-office`,
        )
      ).data,
    enabled: enabled && Number.isFinite(contractId) && contractId > 0,
    staleTime: 5 * 60 * 1000,
  });
}

export function useHandOffToFrontOffice(contractId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (jobIds: number[]) =>
      (
        await api.post<HandoffResult>(`/api/care/contracts/${contractId}/front-office`, {
          job_ids: jobIds,
        })
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: careKeys.frontOffice(contractId) });
      void queryClient.invalidateQueries({ queryKey: careKeys.timeline(contractId) });
      void queryClient.invalidateQueries({ queryKey: ["care", "week"] });
      void queryClient.invalidateQueries({ queryKey: ["care", "redeploy"] });
      void queryClient.invalidateQueries({ queryKey: careKeys.summary });
    },
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
