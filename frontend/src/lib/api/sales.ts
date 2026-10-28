// Sprzedaż (Atlas → NEXUS, 26.10.2026) — firmy, szanse, kontakty, aktywności.
//
// Lustro `backend/app/api/sales_*.py`. Odczyt wymaga „Sprzedaż: podgląd”, zapis
// „Sprzedaż: edycja”; opiekuna zmienia obecny opiekun albo admin (403 z API).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type CompanyLifecycle =
  | "lead"
  | "prospect"
  | "opportunity"
  | "customer"
  | "churned"
  | "disqualified";
export type CompanyStatus = "active" | "inactive" | "do_not_contact";
export type CompanyTier = "strategic" | "enterprise" | "mid_market" | "smb";
export type OpportunityStatus = "open" | "won" | "lost";
export type StageOutcome = OpportunityStatus;
export type ServiceLine = "bodyleasing" | "subscription" | "core_solutions";
export type ActivityKind = "call" | "email" | "meeting" | "task" | "note";
export type ContactRole =
  | "decision_maker"
  | "economic_buyer"
  | "champion"
  | "influencer"
  | "blocker"
  | "end_user";
export type PeopleRelationship = "via_us" | "current" | "past" | "unknown";

export const LIFECYCLE_LABELS: Record<CompanyLifecycle, string> = {
  lead: "Lead",
  prospect: "Potencjalny klient",
  opportunity: "W rozmowach",
  customer: "Klient",
  churned: "Były klient",
  disqualified: "Odrzucona",
};
export const COMPANY_STATUS_LABELS: Record<CompanyStatus, string> = {
  active: "Aktywna",
  inactive: "Nieaktywna",
  do_not_contact: "Nie kontaktować",
};
export const TIER_LABELS: Record<CompanyTier, string> = {
  strategic: "Strategiczna",
  enterprise: "Duża",
  mid_market: "Średnia",
  smb: "Mała",
};
export const SERVICE_LINE_LABELS: Record<ServiceLine, string> = {
  bodyleasing: "Body leasing",
  subscription: "Abonament",
  core_solutions: "Core Solutions",
};
export const ACTIVITY_KIND_LABELS: Record<ActivityKind, string> = {
  call: "Telefon",
  email: "Mail",
  meeting: "Spotkanie",
  task: "Zadanie",
  note: "Notatka",
};
export const CONTACT_ROLE_LABELS: Record<ContactRole, string> = {
  decision_maker: "Decydent",
  economic_buyer: "Budżet",
  champion: "Nasz orędownik",
  influencer: "Wpływa na decyzję",
  blocker: "Blokuje",
  end_user: "Użytkownik",
};
export const RELATIONSHIP_LABELS: Record<PeopleRelationship, string> = {
  via_us: "Pracowali tam przez nas",
  current: "Pracują tam teraz",
  past: "Pracowali tam kiedyś",
  unknown: "Bez dat w CV",
};

export interface Ref {
  id: number;
  name: string;
}

export interface SalesCompany {
  id: number;
  name: string;
  legal_name: string | null;
  nip: string | null;
  krs: string | null;
  regon: string | null;
  domain: string | null;
  website_url: string | null;
  linkedin_url: string | null;
  industry: string | null;
  size_range: string | null;
  hq_city: string | null;
  hq_country: string | null;
  description: string | null;
  lifecycle_stage: CompanyLifecycle;
  tier: CompanyTier | null;
  status: CompanyStatus;
  tags: string[];
  source: string | null;
  parent: Ref | null;
  client: Ref | null;
  owner: Ref | null;
  /** Opiekun z Atlasa bez konta w NEXUSIE — do przypisania na konto. */
  owner_label: string | null;
  /** Tag „atlas: do przejrzenia” — firma przeszła import warunkowo. */
  needs_review: boolean;
  open_opportunities: number;
  open_value: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SalesCompanyList {
  items: SalesCompany[];
  total: number;
}

export interface CompanyFilters {
  q?: string;
  lifecycle?: CompanyLifecycle | "";
  status?: CompanyStatus | "";
  owner_id?: number | null;
  owner_label?: string | null;
  review?: boolean;
  tag?: string | null;
  archived?: boolean;
  offset?: number;
}

export interface CompanyInput {
  name?: string;
  legal_name?: string | null;
  nip?: string | null;
  domain?: string | null;
  website_url?: string | null;
  linkedin_url?: string | null;
  industry?: string | null;
  size_range?: string | null;
  hq_city?: string | null;
  description?: string | null;
  lifecycle_stage?: CompanyLifecycle;
  tier?: CompanyTier | null;
  status?: CompanyStatus;
  parent_company_id?: number | null;
  owner_user_id?: number | null;
  tags?: string[];
  allow_duplicate?: boolean;
}

export interface DuplicateCompany {
  id: number;
  name: string;
  nip: string | null;
}

export interface Stage {
  id: number;
  key: string;
  name: string;
  position: number;
  probability: number;
  outcome: StageOutcome;
  qualifies: boolean;
  color: string | null;
}

export interface Pipeline {
  id: number;
  key: string;
  name: string;
  is_default: boolean;
  stages: Stage[];
}

export interface OpportunityRole {
  title: string;
  count: number;
  seniority?: string | null;
  skills?: string[];
}

export interface Opportunity {
  id: number;
  title: string;
  description: string | null;
  company: Ref;
  pipeline_id: number;
  stage: Stage;
  status: OpportunityStatus;
  service_line: ServiceLine | null;
  value: string | null;
  mrr_value: string | null;
  one_off_value: string | null;
  margin_pct: string | null;
  currency: string;
  contract_months: number | null;
  probability: number;
  weighted_value: string | null;
  expected_close_date: string | null;
  qualified_at: string | null;
  won_at: string | null;
  lost_at: string | null;
  lost_reason: string | null;
  primary_contact_id: number | null;
  roles: OpportunityRole[];
  source: string | null;
  campaign: string | null;
  tags: string[];
  owner: Ref | null;
  last_activity_at: string | null;
  keep_open_until: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface OpportunityContact {
  id: number;
  full_name: string;
  title: string | null;
  email: string | null;
  phone: string | null;
  role: ContactRole | null;
}

export type DecisionOurRole =
  | "decision_maker"
  | "economic_buyer"
  | "champion"
  | "influencer"
  | "blocker"
  | "end_user";

export interface DecisionMapEntry {
  name: string;
  role_in_company?: string | null;
  our_role?: DecisionOurRole | null;
  decision_level?: number | null;
  contact_status?: "not_contacted" | "in_progress" | "first_contact" | "regular_dialog" | null;
  last_contact_at?: string | null;
  notes?: string | null;
  email?: string | null;
  phone?: string | null;
  linkedin_url?: string | null;
  nexus_contact_id?: number | null;
}

export interface ItFactory {
  decision_map?: DecisionMapEntry[];
  purchasing_process?: {
    description?: string | null;
    decision_cycle_months?: number | null;
    rfp_frequency?: "yearly" | "biennial" | "ad_hoc" | null;
    vendor_entry_requirements?: string | null;
    milestones?: Record<string, string | null>;
  } | null;
  next_step?: string | null;
  next_step_due?: string | null;
  decision_map_completeness?: number | null;
  process_completeness?: number | null;
  updated_at?: string | null;
}

/** Dane z Atlasa, które NEXUS pokazuje tylko do odczytu (Fabryki IT, produkty). */
export interface AtlasMotion {
  it_factory: ItFactory | null;
  meddic: Record<string, unknown> | null;
  products: string[];
  subscription_items: Record<string, unknown>[];
}

export interface OpportunityDetail extends Opportunity {
  contacts: OpportunityContact[];
  atlas_motion: AtlasMotion | null;
}

export type OpportunitySort = "updated" | "value" | "close" | "activity" | "created";

export interface OpportunityList {
  items: Opportunity[];
  total: number;
}

export interface OpportunityFilters {
  pipeline_id?: number | null;
  company_id?: number | null;
  owner_id?: number | null;
  status?: OpportunityStatus | "";
  q?: string;
  archived?: boolean;
  sort?: OpportunitySort;
}

export interface OpportunityInput {
  company_id?: number;
  title?: string;
  description?: string | null;
  pipeline_id?: number | null;
  stage_id?: number | null;
  service_line?: ServiceLine | null;
  value?: string | null;
  mrr_value?: string | null;
  one_off_value?: string | null;
  margin_pct?: string | null;
  contract_months?: number | null;
  expected_close_date?: string | null;
  primary_contact_id?: number | null;
  roles?: OpportunityRole[];
  source?: string | null;
  owner_user_id?: number | null;
}

export interface ContactCompanyLink {
  company_id: number;
  company_name: string;
  role: string | null;
  title: string | null;
  is_primary: boolean;
  is_current: boolean;
}

export interface SalesContact {
  id: number;
  company_id: number | null;
  company_name: string | null;
  full_name: string;
  first_name: string | null;
  last_name: string | null;
  title: string | null;
  email: string | null;
  phone: string | null;
  mobile_phone: string | null;
  linkedin_url: string | null;
  seniority: string | null;
  department: string | null;
  is_executive: boolean;
  notes: string | null;
  source: string | null;
  archived_at: string | null;
  created_at: string;
  companies: ContactCompanyLink[];
}

export interface ContactInput {
  company_id?: number | null;
  full_name?: string;
  first_name?: string | null;
  last_name?: string | null;
  title?: string | null;
  email?: string | null;
  phone?: string | null;
  mobile_phone?: string | null;
  linkedin_url?: string | null;
  is_executive?: boolean;
  notes?: string | null;
}

export interface Activity {
  id: number;
  kind: ActivityKind;
  subject: string | null;
  body: string | null;
  priority: "low" | "medium" | "high" | null;
  due_at: string | null;
  occurred_at: string | null;
  done_at: string | null;
  is_pinned: boolean;
  company: Ref | null;
  opportunity: Ref | null;
  contact: Ref | null;
  assignee: Ref | null;
  author: Ref | null;
  overdue: boolean;
  created_at: string;
  external_source: string | null;
  /** Outlook: link do wiadomości, kierunek maila, czas spotkania/telefonu. */
  web_link: string | null;
  direction: "in" | "out" | null;
  duration_minutes: number | null;
  /** Mail albo spotkanie firmy dołożone do historii szansy. */
  from_company: boolean;
}

export interface ActivityInput {
  kind: ActivityKind;
  company_id?: number | null;
  opportunity_id?: number | null;
  contact_id?: number | null;
  subject?: string | null;
  body?: string | null;
  due_at?: string | null;
  priority?: "low" | "medium" | "high" | null;
  done?: boolean;
}

export type TaskBucket = "open" | "overdue" | "today" | "done";

export interface MatchedPerson {
  candidate_id: number;
  name: string;
  lastname: string;
  relationship: PeopleRelationship;
  title: string | null;
  company_matched: string | null;
  period: { start: string | null; end: string | null } | null;
  email: string | null;
  phone: string | null;
  linkedin: string | null;
  profile_url: string | null;
}

export interface CompanyPeople {
  matched_client: Ref | null;
  counts: Record<PeopleRelationship, number>;
  truncated: boolean;
  people: MatchedPerson[];
  dates_backfill: {
    status?: "running" | "done" | "partial" | "failed";
    total?: number;
    updated?: number;
    finished_at?: string;
  } | null;
}

export const salesKeys = {
  all: ["sales"] as const,
  companies: (filters: CompanyFilters) => ["sales", "companies", filters] as const,
  company: (id: number) => ["sales", "company", id] as const,
  companyPeople: (id: number) => ["sales", "company", id, "people"] as const,
  duplicates: (name: string, nip: string) => ["sales", "duplicates", name, nip] as const,
  pipelines: ["sales", "pipelines"] as const,
  opportunities: (filters: OpportunityFilters) =>
    ["sales", "opportunities", filters] as const,
  opportunity: (id: number) => ["sales", "opportunity", id] as const,
  contacts: (companyId: number | null, q: string, extra?: Record<string, unknown>) =>
    ["sales", "contacts", companyId, q, extra ?? {}] as const,
  activities: (scope: ActivityScope) => ["sales", "activities", scope] as const,
  tasks: (filters: TaskFilters) => ["sales", "tasks", filters] as const,
  summary: (pipelineId: number | null, period: SummaryPeriod) =>
    ["sales", "summary", pipelineId, period] as const,
  ownerLabels: ["sales", "owner-labels"] as const,
  companyDuplicates: ["sales", "company-duplicates"] as const,
};

function clean(params: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue;
    out[key] = typeof value === "string" ? value.trim() : String(value);
  }
  return out;
}

// ── Firmy ─────────────────────────────────────────────────────────────────

export function useSalesCompanies(filters: CompanyFilters, enabled = true) {
  return useQuery({
    queryKey: salesKeys.companies(filters),
    queryFn: async () =>
      (
        await api.get<SalesCompanyList>("/api/sales/companies", {
          params: clean({ ...filters, limit: 50 }),
        })
      ).data,
    enabled,
  });
}

export function useSalesCompany(id: number) {
  return useQuery({
    queryKey: salesKeys.company(id),
    queryFn: async () => (await api.get<SalesCompany>(`/api/sales/companies/${id}`)).data,
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useCompanyDuplicates(name: string, nip: string, excludeId?: number) {
  const term = name.trim();
  return useQuery({
    queryKey: salesKeys.duplicates(term, nip.trim()),
    queryFn: async () =>
      (
        await api.get<DuplicateCompany[]>("/api/sales/companies/duplicates", {
          params: clean({ name: term, nip, exclude_id: excludeId }),
        })
      ).data,
    enabled: term.length >= 3,
    staleTime: 60_000,
  });
}

export interface GroupCompanyPeople {
  company: Ref;
  relation: "parent" | "child";
  /** `null` — tej spółki nie udało się policzyć (limit czasu skanu). */
  counts: Record<PeopleRelationship, number> | null;
}

export function useCompanyGroupPeople(id: number, enabled = true) {
  return useQuery({
    queryKey: [...salesKeys.companyPeople(id), "group"] as const,
    queryFn: async () =>
      (await api.get<GroupCompanyPeople[]>(`/api/sales/companies/${id}/people/group`)).data,
    enabled: enabled && Number.isFinite(id) && id > 0,
    staleTime: 5 * 60 * 1000,
  });
}

export function useCompanyPeople(id: number, enabled = true) {
  return useQuery({
    queryKey: salesKeys.companyPeople(id),
    queryFn: async () =>
      (await api.get<CompanyPeople>(`/api/sales/companies/${id}/people`)).data,
    enabled: enabled && Number.isFinite(id) && id > 0,
    staleTime: 5 * 60 * 1000,
  });
}

function useInvalidateSales() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: salesKeys.all });
}

export function useCreateSalesCompany() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (payload: CompanyInput) =>
      (await api.post<SalesCompany>("/api/sales/companies", payload)).data,
    onSuccess: invalidate,
  });
}

export function useUpdateSalesCompany(id: number) {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (payload: CompanyInput) =>
      (await api.patch<SalesCompany>(`/api/sales/companies/${id}`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useArchiveSalesCompany(id: number) {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (restore: boolean) =>
      (
        await api.post<SalesCompany>(
          `/api/sales/companies/${id}/${restore ? "restore" : "archive"}`,
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useFillCompanyDates(id: number) {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async () =>
      (await api.post<{ scheduled: boolean }>(`/api/sales/companies/${id}/people/dates`))
        .data,
    onSuccess: invalidate,
  });
}

// ── Lejki i szanse ────────────────────────────────────────────────────────

export function usePipelines(enabled = true) {
  return useQuery({
    queryKey: salesKeys.pipelines,
    queryFn: async () => (await api.get<Pipeline[]>("/api/sales/pipelines")).data,
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}

/** Tyle szans wczytuje tablica i lista; więcej = komunikat „pokazujemy N z M”. */
export const OPPORTUNITIES_PAGE = 2000;

export function useOpportunities(filters: OpportunityFilters, enabled = true) {
  return useQuery({
    queryKey: salesKeys.opportunities(filters),
    queryFn: async () =>
      (
        await api.get<OpportunityList>("/api/sales/opportunities", {
          params: clean({ ...filters, limit: OPPORTUNITIES_PAGE }),
        })
      ).data,
    enabled,
  });
}

export function useOpportunity(id: number) {
  return useQuery({
    queryKey: salesKeys.opportunity(id),
    queryFn: async () =>
      (await api.get<OpportunityDetail>(`/api/sales/opportunities/${id}`)).data,
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useCreateOpportunity() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (payload: OpportunityInput) =>
      (await api.post<OpportunityDetail>("/api/sales/opportunities", payload)).data,
    onSuccess: invalidate,
  });
}

export function useUpdateOpportunity(id: number) {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (payload: OpportunityInput) =>
      (await api.patch<OpportunityDetail>(`/api/sales/opportunities/${id}`, payload))
        .data,
    onSuccess: invalidate,
  });
}

export function useMoveOpportunity() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: { id: number; stage_id: number; lost_reason?: string }) =>
      (
        await api.post<OpportunityDetail>(`/api/sales/opportunities/${input.id}/move`, {
          stage_id: input.stage_id,
          lost_reason: input.lost_reason,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useArchiveOpportunity(id: number) {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (restore: boolean) =>
      (
        await api.post<OpportunityDetail>(
          `/api/sales/opportunities/${id}/${restore ? "restore" : "archive"}`,
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useLinkOpportunityContact(id: number) {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: { contact_id: number; role: ContactRole | null; remove?: boolean }) =>
      input.remove
        ? (
            await api.delete<OpportunityDetail>(
              `/api/sales/opportunities/${id}/contacts/${input.contact_id}`,
            )
          ).data
        : (
            await api.put<OpportunityDetail>(
              `/api/sales/opportunities/${id}/contacts/${input.contact_id}`,
              { role: input.role },
            )
          ).data,
    onSuccess: invalidate,
  });
}

// ── Kontakty ──────────────────────────────────────────────────────────────

export interface ContactListOptions {
  executives?: boolean;
  archived?: boolean;
  limit?: number;
  offset?: number;
}

export function useSalesContacts(
  companyId: number | null,
  q = "",
  enabled = true,
  options: ContactListOptions = {},
) {
  return useQuery({
    queryKey: salesKeys.contacts(companyId, q.trim(), { ...options }),
    queryFn: async () =>
      (
        await api.get<{ items: SalesContact[]; total: number }>("/api/sales/contacts", {
          params: clean({ company_id: companyId, q, limit: 200, ...options }),
        })
      ).data,
    enabled,
  });
}

export function useArchiveSalesContact() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post<SalesContact>(`/api/sales/contacts/${id}/archive`)).data,
    onSuccess: invalidate,
  });
}

export function useLinkContactCompany(contactId: number) {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: { company_id: number; role?: string | null; title?: string | null; is_current?: boolean }) =>
      (await api.post<SalesContact>(`/api/sales/contacts/${contactId}/companies`, input)).data,
    onSuccess: invalidate,
  });
}

export function useUnlinkContactCompany(contactId: number) {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (companyId: number) => {
      await api.delete(`/api/sales/contacts/${contactId}/companies/${companyId}`);
    },
    onSuccess: invalidate,
  });
}

export function useCreateSalesContact() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (payload: ContactInput) =>
      (await api.post<SalesContact>("/api/sales/contacts", payload)).data,
    onSuccess: invalidate,
  });
}

export function useUpdateSalesContact(id: number) {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (payload: ContactInput) =>
      (await api.patch<SalesContact>(`/api/sales/contacts/${id}`, payload)).data,
    onSuccess: invalidate,
  });
}

// ── Aktywności i zadania ──────────────────────────────────────────────────

export interface ActivityScope {
  company_id?: number;
  opportunity_id?: number;
  /** Na szansie: dołóż maile i spotkania firmy z Outlooka (jak karta szansy w Atlasie). */
  with_company_mail?: boolean;
  limit?: number;
}

export function useSalesActivities(scope: ActivityScope, enabled = true) {
  return useQuery({
    queryKey: salesKeys.activities(scope),
    queryFn: async () =>
      (await api.get<Activity[]>("/api/sales/activities", { params: clean({ ...scope }) })).data,
    enabled: enabled && Boolean(scope.company_id || scope.opportunity_id),
  });
}

export interface TaskFilters {
  scope: "mine" | "team";
  bucket: TaskBucket;
  kind?: "task" | "call" | "";
  limit?: number;
}

export interface TaskList {
  items: Activity[];
  total: number;
}

export function useSalesTasks(filters: TaskFilters) {
  return useQuery({
    queryKey: salesKeys.tasks(filters),
    queryFn: async () =>
      (await api.get<TaskList>("/api/sales/activities/tasks", { params: clean({ ...filters }) }))
        .data,
  });
}

export function useCompleteTasks() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (ids: number[]) =>
      (await api.post<{ updated: number }>("/api/sales/activities/tasks/complete", { ids })).data,
    onSuccess: invalidate,
  });
}

export function useUpdateActivity(id: number) {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (payload: Partial<ActivityInput> & { assignee_user_id?: number | null }) =>
      (await api.patch<Activity>(`/api/sales/activities/${id}`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useCreateActivity() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (payload: ActivityInput) =>
      (await api.post<Activity>("/api/sales/activities", payload)).data,
    onSuccess: invalidate,
  });
}

export function useCompleteActivity() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: { id: number; reopen?: boolean }) =>
      (
        await api.post<Activity>(
          `/api/sales/activities/${input.id}/${input.reopen ? "reopen" : "done"}`,
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useDeleteActivity() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/sales/activities/${id}`);
    },
    onSuccess: invalidate,
  });
}

// ── Powiązanie z klientem NEXUSA (decyzja 27.10.2026) ─────────────────────

export interface ClientSalesSummary {
  company: Ref | null;
  opportunities: {
    id: number;
    title: string;
    stage: string;
    status: OpportunityStatus;
    value: string | null;
    currency: string;
    won_at: string | null;
    updated_at: string;
  }[];
}

export function useClientOptions(q: string) {
  const term = q.trim();
  return useQuery({
    queryKey: ["sales", "client-options", term] as const,
    queryFn: async () =>
      (await api.get<Ref[]>("/api/sales/clients/options", { params: { q: term } })).data,
    enabled: term.length >= 2,
    staleTime: 60_000,
  });
}

export function useLinkClient(companyId: number) {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (clientId: number | null) =>
      (await api.put<Ref | null>(`/api/sales/clients/link/${companyId}`, { client_id: clientId }))
        .data,
    onSuccess: invalidate,
  });
}

export function useClientSalesSummary(clientId: number, enabled = true) {
  return useQuery({
    queryKey: ["sales", "client-summary", clientId] as const,
    queryFn: async () =>
      (await api.get<ClientSalesSummary>(`/api/sales/clients/${clientId}/summary`)).data,
    enabled: enabled && Number.isFinite(clientId) && clientId > 0,
  });
}

// ── Leady ─────────────────────────────────────────────────────────────────

export type LeadSource = "job_board" | "linkedin" | "press" | "manual" | "atlas";
export type LeadStatus = "new" | "contacted" | "converted" | "dismissed";

export const LEAD_SOURCE_LABELS: Record<LeadSource, string> = {
  job_board: "Ogłoszenia",
  linkedin: "LinkedIn",
  press: "Prasa",
  manual: "Ręcznie",
  atlas: "Z Atlasa",
};
export const LEAD_STATUS_LABELS: Record<LeadStatus, string> = {
  new: "Nowe",
  contacted: "W kontakcie",
  converted: "Szanse",
  dismissed: "Odrzucone",
};

export interface Lead {
  id: number;
  source: LeadSource;
  status: LeadStatus;
  title: string;
  summary: string | null;
  company_name: string | null;
  company_id: number | null;
  url: string | null;
  score: number;
  signal_at: string | null;
  opportunity_id: number | null;
  dismissed_reason: string | null;
  created_at: string;
  payload: Record<string, unknown>;
}

export interface LeadList {
  items: Lead[];
  total: number;
  counts: Record<LeadStatus, number>;
}

export function useLeads(filters: { status: LeadStatus; source?: LeadSource | ""; q?: string }) {
  return useQuery({
    queryKey: ["sales", "leads", filters] as const,
    queryFn: async () =>
      (await api.get<LeadList>("/api/sales/leads", { params: clean({ ...filters }) })).data,
  });
}

export function useCreateLead() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (payload: {
      title: string;
      company_name: string;
      summary?: string | null;
      url?: string | null;
    }) => (await api.post<Lead>("/api/sales/leads", payload)).data,
    onSuccess: invalidate,
  });
}

export function useUpdateLead() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: { id: number; status: "new" | "contacted" | "dismissed"; dismissed_reason?: string }) =>
      (
        await api.patch<Lead>(`/api/sales/leads/${input.id}`, {
          status: input.status,
          dismissed_reason: input.dismissed_reason,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useConvertLead() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (id: number) =>
      (
        await api.post<{ opportunity_id: number; company_id: number }>(
          `/api/sales/leads/${id}/convert`,
          {},
        )
      ).data,
    onSuccess: invalidate,
  });
}

export interface RegistryCompany {
  name: string | null;
  nip: string | null;
  regon: string | null;
  krs: string | null;
  address: string | null;
  hq_city: string | null;
  source: string | null;
}

/** „Pobierz z rejestru” — jednorazowe zapytanie na klik, nie zapytanie w tle. */
export function useRegistryLookup() {
  return useMutation({
    mutationFn: async (nip: string) =>
      (await api.get<RegistryCompany>("/api/sales/companies/registry", { params: { nip } }))
        .data,
  });
}

// ── Pliki ─────────────────────────────────────────────────────────────────

export interface SalesFile {
  id: number;
  filename: string;
  content_type: string | null;
  size_bytes: number | null;
  folder: string | null;
  company_id: number | null;
  opportunity_id: number | null;
  uploaded_by: string | null;
  uploaded_by_user_id: number | null;
  created_at: string;
}

export type FileOwner = { company_id: number } | { opportunity_id: number };

export function useSalesFiles(owner: FileOwner) {
  return useQuery({
    queryKey: ["sales", "files", owner] as const,
    queryFn: async () =>
      (await api.get<SalesFile[]>("/api/sales/files", { params: owner })).data,
  });
}

export function useUploadSalesFile(owner: FileOwner) {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      for (const [key, value] of Object.entries(owner)) form.append(key, String(value));
      return (
        await api.post<SalesFile>("/api/sales/files", form, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

export function useDeleteSalesFile() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/sales/files/${id}`);
    },
    onSuccess: invalidate,
  });
}

// ── Podsumowanie, opiekunowie z Atlasa, duplikaty (audyt importu 28.10.2026) ──

export type SummaryPeriod = "all" | "quarter" | "next_quarter";

export interface SalesSummaryOwner {
  owner: Ref | null;
  open: number;
  value: string;
  weighted: string;
  mrr: string;
  stale: number;
  no_close: number;
}

export interface SalesSummary {
  pipeline: Ref;
  open_count: number;
  value: string;
  weighted: string;
  mrr: string;
  stale_count: number;
  by_owner: SalesSummaryOwner[];
  by_stage: { stage: { id: number; name: string; position: number }; count: number; value: string }[];
}

export function useSalesSummary(pipelineId: number | null, period: SummaryPeriod, enabled = true) {
  return useQuery({
    queryKey: salesKeys.summary(pipelineId, period),
    queryFn: async () =>
      (
        await api.get<SalesSummary>("/api/sales/summary", {
          params: clean({ pipeline_id: pipelineId, period }),
        })
      ).data,
    enabled,
  });
}

export interface OwnerLabel {
  label: string;
  companies: number;
}

export function useOwnerLabels(enabled = true) {
  return useQuery({
    queryKey: salesKeys.ownerLabels,
    queryFn: async () =>
      (await api.get<OwnerLabel[]>("/api/sales/companies/owner-labels")).data,
    enabled,
    staleTime: 60_000,
  });
}

export function useAssignOwnerLabel() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: { label: string; owner_user_id: number }) =>
      (
        await api.post<{ companies: number; opportunities: number }>(
          "/api/sales/companies/owner-labels/assign",
          input,
        )
      ).data,
    onSuccess: invalidate,
  });
}

export interface DuplicateGroup {
  key: string;
  reason: "nip" | "name";
  companies: { id: number; name: string; nip: string | null; open_opportunities: number }[];
}

export function useCompanyDuplicateGroups(enabled = true) {
  return useQuery({
    queryKey: salesKeys.companyDuplicates,
    queryFn: async () =>
      (await api.get<DuplicateGroup[]>("/api/sales/companies/duplicates")).data,
    enabled,
  });
}

export function useMergeCompany() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: { target_id: number; source_id: number }) =>
      (
        await api.post<SalesCompany>(`/api/sales/companies/${input.target_id}/merge`, {
          source_id: input.source_id,
        })
      ).data,
    onSuccess: invalidate,
  });
}
