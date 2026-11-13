// Sprzedaż (Atlas → NEXUS, 26.10.2026) — firmy, szanse, kontakty, aktywności.
//
// Lustro `backend/app/api/sales_*.py`. Odczyt wymaga „Sprzedaż: podgląd”, zapis
// „Sprzedaż: edycja”; opiekuna zmienia obecny opiekun albo admin (403 z API).

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";

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

export interface OpportunityStep {
  kind: "task" | "call" | "meeting";
  at: string;
  subject: string | null;
}

export interface OpportunityLastContact {
  kind: "call" | "email" | "meeting" | "note";
  direction: "in" | "out" | null;
  at: string;
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
  /** Ostatni dotyk (definicja w backendzie: services/sales/touch.py). */
  last_touch_at: string;
  /** Krok, zaległość i ostatni kontakt: definicja w services/sales/next_step.py. */
  next_step: OpportunityStep | null;
  overdue_step: OpportunityStep | null;
  last_contact: OpportunityLastContact | null;
  /** Klient napisał ostatni, a kroku nie ma. */
  waiting_for_reply: boolean;
  /** Brak kroku na szansie założonej albo ruszonej po wdrożeniu zasad. */
  step_alarm: boolean;
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
  /** Osoba nie życzy sobie kontaktu: numer i mail nie są klikalne. */
  do_not_contact_at: string | null;
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
  /** Skrót treści wpisu: zmienia się przy każdej zmianie osoby. */
  key: string;
  nexus_contact_id?: number | null;
  /** Pola, których wpis nie ma, pokazane z kontaktu tej osoby. */
  from_contact?: DecisionFromContactField[];
  /** Sprzeciw wobec kontaktu: z kontaktu albo z samego wpisu na mapie. */
  do_not_contact?: boolean;
  /** Wpis z importu listy (Leady → „Lista z researchu”): skąd pochodzi i od kiedy. */
  source?: string | null;
  source_label?: string | null;
  source_url?: string | null;
  source_added_at?: string | null;
  /** Data publikacji źródła (osoby od bota, „Grok Bot”). */
  source_published_at?: string | null;
  source_confidence?: "confirmed" | "to_verify" | null;
}

export type DecisionFromContactField = "email" | "phone" | "linkedin_url" | "notes";

export type DecisionPersonInput = Partial<
  Pick<
    DecisionMapEntry,
    | "name"
    | "role_in_company"
    | "our_role"
    | "decision_level"
    | "contact_status"
    | "last_contact_at"
    | "notes"
    | "email"
    | "phone"
    | "linkedin_url"
  >
>;

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
  nexus_updated_at?: string | null;
}

/** Dane z Atlasa na karcie szansy (Fabryki IT, produkty); mapę da się poprawiać. */
export interface AtlasMotion {
  it_factory: ItFactory | null;
  meddic: Record<string, unknown> | null;
  products: string[];
  subscription_items: Record<string, unknown>[];
}

export type OpportunityEventKind =
  | "created"
  | "updated"
  | "archived"
  | "restored"
  | "company_merged";

/** Wpis „Historii zmian” szansy: kto, kiedy, które pole, co było i co jest. */
export interface OpportunityEvent {
  id: number;
  kind: OpportunityEventKind;
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  /** Nazwa etapu, opiekuna albo firmy dla pól z identyfikatorem. */
  old_label: string | null;
  new_label: string | null;
  user: Ref | null;
  created_at: string;
}

export interface OpportunityDetail extends Opportunity {
  contacts: OpportunityContact[];
  atlas_motion: AtlasMotion | null;
  decision_map_enabled: boolean;
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
  service_line?: ServiceLine | null;
  created_from?: string | null;
  created_to?: string | null;
  offers_only?: boolean;
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
  campaign?: string | null;
  owner_user_id?: number | null;
  /** „Odłóż do…” z zakładki Oferty; ten sam dzień chroni też przed automatem archiwizacji. */
  keep_open_until?: string | null;
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
  /** Osoba nie życzy sobie kontaktu: numer i mail nie są klikalne. */
  do_not_contact_at?: string | null;
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
  /** Wynik rozmowy zapisanej z karty szansy. */
  outcome?: CallOutcome | QueueOnlyOutcome | null;
  /** Mail albo spotkanie firmy dołożone do historii szansy. */
  from_company: boolean;
}

export type CallOutcome =
  | "connected"
  | "no_answer"
  | "call_back"
  | "wants_offer"
  | "not_now"
  | "do_not_contact";

/** Wyniki, które zapisuje tylko kolejka dzwonienia (ten sam słownik co backend). */
export type QueueOnlyOutcome = "offer_sent" | "meeting_booked" | "not_interested" | "bad_contact";

export const CALL_OUTCOME_LABELS: Record<CallOutcome | QueueOnlyOutcome, string> = {
  connected: "Dodzwoniłem",
  no_answer: "Nie odebrał",
  call_back: "Oddzwonić",
  wants_offer: "Prosi o ofertę",
  not_now: "Nie teraz",
  do_not_contact: "Nie kontaktować",
  offer_sent: "Oferta ogólna wysłana",
  meeting_booked: "Umówione spotkanie",
  not_interested: "Nie zainteresowany",
  bad_contact: "Zły numer / brak danych",
};

export type TimelineScope = "opportunity" | "company" | "other_opportunity";

export interface TimelineItem extends Activity {
  scope: TimelineScope;
  /** Skąd wpis: po sklejeniu duplikatów może być kilka źródeł. */
  sources: string[];
  /** Spotkanie z transkryptem Teams: aktywność z Outlooka, przy której leży transkrypt. */
  transcript_activity_id?: number | null;
  transcript_summary?: string | null;
  /** Organizator spotkania albo admin z „Sprzedaż: edycja”. */
  can_send_client_summary?: boolean;
  client_mail_sent_at?: string | null;
}

export interface OpportunityTimeline {
  items: TimelineItem[];
  counts: Record<TimelineScope | "all", number>;
}

export interface ActivityInput {
  kind: ActivityKind;
  company_id?: number | null;
  opportunity_id?: number | null;
  contact_id?: number | null;
  subject?: string | null;
  body?: string | null;
  due_at?: string | null;
  /** Termin spotkania (także przyszły): z niego liczy się krok szansy. */
  occurred_at?: string | null;
  priority?: "low" | "medium" | "high" | null;
  done?: boolean;
  /** Jawne przypisanie zadania (np. powrót do firmy u opiekuna leada). */
  assignee_user_id?: number | null;
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
  /** Dzień dodania do bazy (kalendarz firmy), „RRRR-MM-DD”. */
  added_at: string | null;
  decision_role: boolean;
  cv_stale: boolean;
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
  /** Prawda tylko po udanym zapisie odczytu listy osób w dzienniku. */
  read_logged: boolean;
  own_company: boolean;
}

export type AliasStatus = "joined" | "rejected";

export interface AliasDecision {
  id: number;
  name: string;
  status: AliasStatus;
}

export interface AliasVariant {
  key: string;
  name: string;
  people: number;
  current: number;
}

export interface CompanyAliases {
  decisions: AliasDecision[];
  suggestions: AliasVariant[];
  other_count: number;
  other_min: number;
  other_max: number;
  own_cards: { id: number; name: string; current: number }[];
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
  opportunityHistory: (id: number) => ["sales", "opportunity", id, "history"] as const,
  contacts: (companyId: number | null, q: string, extra?: Record<string, unknown>) =>
    ["sales", "contacts", companyId, q, extra ?? {}] as const,
  activities: (scope: ActivityScope) => ["sales", "activities", scope] as const,
  timeline: (opportunityId: number) => ["sales", "activities", "timeline", opportunityId] as const,
  tasks: (filters: TaskFilters) => ["sales", "tasks", filters] as const,
  summary: (pipelineId: number | null, period: SummaryPeriod) =>
    ["sales", "summary", pipelineId, period] as const,
  ownerLabels: ["sales", "owner-labels"] as const,
  ownerCandidates: ["sales", "owner-candidates"] as const,
  companyDuplicates: ["sales", "company-duplicates"] as const,
  myDay: ["sales", "my-day"] as const,
  offers: (filters: OfferFilters) => ["sales", "offers", filters] as const,
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

export type MyDaySectionKey = "meetings" | "reply" | "overdue" | "offers";

export interface MyDayPerson {
  id: number;
  name: string;
  title: string | null;
  phone: string | null;
  email: string | null;
}

export interface MyDayRow {
  key: string;
  section: MyDaySectionKey;
  company: Ref;
  opportunity: { id: number; title: string } | null;
  activity_id: number | null;
  kind: "task" | "call" | null;
  subject: string | null;
  at: string;
  days: number;
  amount: string | null;
  currency: string;
  open_opportunities: number;
  duration_minutes: number | null;
  web_link: string | null;
  do_not_contact: boolean;
  person: MyDayPerson | null;
  people_without_phone: MyDayPerson[];
  /** Spotkanie z kalendarza przypięte do szansy przez automat (firma miała jedną otwartą szansę). */
  auto_pinned?: boolean;
  /** Spotkanie z Outlooka przy firmie bez otwartej szansy: po nim można ją założyć. */
  can_create_opportunity?: boolean;
}

export interface MyDayPrepEntry {
  kind: ActivityKind;
  direction: "in" | "out" | null;
  at: string;
  subject: string | null;
  /** Dni kalendarzowe (kalendarz firmy) od tego wpisu. */
  days: number;
}

export interface MyDayPrep {
  activity_id: number;
  company: Ref;
  subject: string | null;
  at: string;
  duration_minutes: number | null;
  open_opportunities: number;
  can_create_opportunity: boolean;
  history: MyDayPrepEntry[];
  contacts: MyDayPerson[];
}

export interface MyDaySignal {
  lead_id: number;
  company: Ref;
  title: string;
  strength: SignalStrength | null;
  type: SignalType | null;
  signal_at: string | null;
}

export interface MyDay {
  today: string;
  counts: Record<MyDaySectionKey | "older_tasks", number> & { signals?: number };
  meetings: MyDayRow[];
  reply: MyDayRow[];
  overdue: MyDayRow[];
  offers: MyDayRow[];
  prep: MyDayPrep | null;
  /** Nowe sygnały z bota researchu (najwyżej trzy); pusta lista przy wyłączonej fladze. */
  signals?: MyDaySignal[];
}

/** Kolejka „Mój dzień” zalogowanej osoby. */
export function useMyDay() {
  return useQuery({
    queryKey: salesKeys.myDay,
    queryFn: async () => (await api.get<MyDay>("/api/sales/my-day")).data,
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

export function useCompanyAliases(id: number, enabled = true) {
  return useQuery({
    queryKey: [...salesKeys.companyPeople(id), "aliases"] as const,
    queryFn: async () =>
      (await api.get<CompanyAliases>(`/api/sales/companies/${id}/people/aliases`)).data,
    enabled: enabled && Number.isFinite(id) && id > 0,
    staleTime: 5 * 60 * 1000,
  });
}

/** Klucz listy osób obejmuje też nazwy z CV i grupę, więc liczby się przeliczają. */
function useInvalidateCompanyPeople(id: number) {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: salesKeys.companyPeople(id) });
}

export function useDecideCompanyAlias(id: number) {
  const invalidate = useInvalidateCompanyPeople(id);
  return useMutation({
    mutationFn: async (payload: { name: string; status: AliasStatus }) =>
      (await api.post<AliasDecision>(`/api/sales/companies/${id}/people/aliases`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useUndoCompanyAlias(id: number) {
  const invalidate = useInvalidateCompanyPeople(id);
  return useMutation({
    mutationFn: async (aliasId: number) => {
      await api.delete(`/api/sales/companies/${id}/people/aliases/${aliasId}`);
    },
    onSuccess: invalidate,
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

export function useOpportunityHistory(id: number, enabled = true) {
  return useQuery({
    queryKey: salesKeys.opportunityHistory(id),
    queryFn: async () =>
      (await api.get<OpportunityEvent[]>(`/api/sales/opportunities/${id}/history`)).data,
    enabled: enabled && Number.isFinite(id) && id > 0,
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

export type OpportunityBulkAction =
  | { action: "plan"; days: number; subject?: string }
  | { action: "owner"; owner_user_id: number }
  | { action: "close"; stage_key?: string; lost_reason?: string };

export interface OpportunityBulkResult {
  done: number[];
  skipped: { id: number; title: string | null; reason: string }[];
}

/** Tyle szans przyjmuje jeden zapis (`MAX_IDS` w `backend/app/services/sales/bulk.py`). */
export const OPPORTUNITY_BULK_MAX_IDS = 200;

/**
 * Zapis wielu szans w paczkach po `OPPORTUNITY_BULK_MAX_IDS`, bo lista zaznacza do
 * `OPPORTUNITIES_PAGE` szans naraz. Wynik jest jeden: błąd pierwszej paczki to błąd
 * całego zapisu (nic się nie zapisało), a po błędzie późniejszej zapisane zostają,
 * reszta wraca jako pominięta z powodem.
 */
export async function postOpportunityBulk({
  ids,
  ...action
}: { ids: number[] } & OpportunityBulkAction): Promise<OpportunityBulkResult> {
  const result: OpportunityBulkResult = { done: [], skipped: [] };
  for (let start = 0; start < ids.length; start += OPPORTUNITY_BULK_MAX_IDS) {
    const chunk = ids.slice(start, start + OPPORTUNITY_BULK_MAX_IDS);
    try {
      const { data } = await api.post<OpportunityBulkResult>("/api/sales/opportunities/bulk", { ids: chunk, ...action });
      result.done.push(...data.done);
      result.skipped.push(...data.skipped);
    } catch (error) {
      if (start === 0) throw error;
      const reason = `nie zapisano: ${apiErrorMessage(error, "błąd zapisu")}`;
      result.skipped.push(...ids.slice(start).map((id) => ({ id, title: null, reason })));
      break;
    }
  }
  return result;
}

/** Akcja z listy Szans dla wielu zaznaczonych szans (`POST /api/sales/opportunities/bulk`). */
export function useBulkOpportunities() {
  const invalidate = useInvalidateSales();
  return useMutation({ mutationFn: postOpportunityBulk, onSuccess: invalidate });
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

// ── Oferty: „W toku” i „Do decyzji” (zasady w services/sales/offers.py) ────

export type OfferScope = "mine" | "unowned" | "all";
export type OfferSection = "in_progress" | "to_decide";

export interface OfferStep {
  /** Zadanie albo telefon do odhaczenia; spotkanie z kalendarza go nie ma. */
  activity_id: number | null;
  kind: OpportunityStep["kind"];
  at: string;
  subject: string | null;
  overdue: boolean;
}

export interface OfferRow {
  id: number;
  title: string;
  company: Ref;
  pipeline_id: number;
  pipeline_name: string;
  stage: { id: number; key: string; name: string };
  /** Fałsz: szansa z innego etapu, która jest tu tylko dlatego, że nie ma opiekuna. */
  is_offer: boolean;
  owner: Ref | null;
  /** Opiekun jest i pracuje w Sprzedaży; bez tego pozycję można przejąć. */
  owner_in_sales: boolean;
  mrr_value: string | null;
  currency: string;
  idle_since: string;
  idle_days: number;
  expected_close_date: string | null;
  close_overdue: boolean;
  keep_open_until: string | null;
  postponed: boolean;
  section: OfferSection;
  reason: "owner_left" | "idle" | null;
  step: OfferStep | null;
  /**
   * Punkty bota o firmie: tylko w „Do decyzji” i z włączonym kanałem sygnałów.
   * Pusta lista = bot sprawdził firmę i nic nowego nie znalazł; `null` = nic nie pokazuj.
   */
  bot_points: OfferBotPoints | null;
}

export interface OfferBotPoints {
  generated_at: string;
  points: TalkingPoint[];
}

export interface OfferSectionTotals {
  count: number;
  mrr: string;
}

export interface Offers {
  /** Zakres, który serwer zastosował: bez parametru wybiera go sam. */
  scope: OfferScope;
  items: OfferRow[];
  totals: Record<OfferScope, Record<OfferSection, OfferSectionTotals>>;
}

export interface OfferFilters {
  scope?: OfferScope;
  q?: string;
}

export function useOffers(filters: OfferFilters) {
  return useQuery({
    queryKey: salesKeys.offers(filters),
    queryFn: async () =>
      (await api.get<Offers>("/api/sales/offers", { params: clean({ ...filters }) })).data,
    // Zmiana zakresu albo frazy nie zeruje liczników na czas zapytania.
    placeholderData: keepPreviousData,
  });
}

/** „Przejmij”: klikający zostaje opiekunem szansy, której nikt ze Sprzedaży nie prowadzi. */
export function useTakeOverOpportunity() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post<{ id: number; owner: Ref }>(`/api/sales/opportunities/${id}/take-over`)).data,
    onSuccess: invalidate,
  });
}

export interface CallLogInput {
  opportunity_id: number;
  outcome: CallOutcome;
  contact_id?: number;
  person_key?: string;
  note?: string;
}

/** Wynik rozmowy z karty szansy; „Nie kontaktować” zapisuje też sprzeciw. */
export function useLogCall() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async ({ opportunity_id, ...payload }: CallLogInput) =>
      (
        await api.post<OpportunityDetail>(
          `/api/sales/opportunities/${opportunity_id}/calls`,
          payload,
        )
      ).data,
    // Bez czekania na przeładowanie karty: okno „Co dalej” ma się otworzyć od razu.
    onSuccess: () => {
      void invalidate();
    },
  });
}

export interface CompanyCallInput {
  company_id: number;
  outcome: CallOutcome;
  contact_id?: number;
  note?: string;
}

/** Wynik rozmowy przy firmie bez szansy (zaległe zadanie założone przy samej firmie). */
export function useLogCompanyCall() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async ({ company_id, ...payload }: CompanyCallInput) => {
      await api.post(`/api/sales/companies/${company_id}/calls`, payload);
    },
    onSuccess: () => {
      void invalidate();
    },
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

/**
 * Karta dostaje nową mapę z odpowiedzi, a reszta Sprzedaży odświeża się w tle:
 * czekanie na „Kogo znamy” trzymałoby okno otwarte po udanym zapisie.
 */
function useDecisionMapCache(opportunityId: number) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateSales();
  return {
    onSuccess: (detail: OpportunityDetail) => {
      queryClient.setQueryData(salesKeys.opportunity(opportunityId), detail);
      void invalidate();
    },
    // Po 409 kolejne otwarcie osoby ma już jej nowy stan i klucz.
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: salesKeys.opportunity(opportunityId) });
    },
  };
}

export function useSaveDecisionPerson(opportunityId: number) {
  const cache = useDecisionMapCache(opportunityId);
  return useMutation({
    mutationFn: async (input: { key: string | null; payload: DecisionPersonInput }) => {
      const url = `/api/sales/opportunities/${opportunityId}/decision-map`;
      return input.key
        ? (await api.patch<OpportunityDetail>(`${url}/${input.key}`, input.payload)).data
        : (await api.post<OpportunityDetail>(url, input.payload)).data;
    },
    ...cache,
  });
}

export function useRemoveDecisionPerson(opportunityId: number) {
  const cache = useDecisionMapCache(opportunityId);
  return useMutation({
    mutationFn: async (key: string) =>
      (
        await api.delete<OpportunityDetail>(
          `/api/sales/opportunities/${opportunityId}/decision-map/${key}`,
        )
      ).data,
    ...cache,
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

/** Wspólna oś szansy i firmy: etykieta skąd wpis, duplikaty sklejone po stronie serwera. */
export function useOpportunityTimeline(opportunityId: number, enabled = true) {
  return useQuery({
    queryKey: salesKeys.timeline(opportunityId),
    queryFn: async () =>
      (
        await api.get<OpportunityTimeline>("/api/sales/activities/timeline", {
          params: { opportunity_id: opportunityId },
        })
      ).data,
    enabled: enabled && Number.isFinite(opportunityId) && opportunityId > 0,
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

export type MeetingDecision = "linked" | "client" | "internal" | "create" | "pin" | "choose" | "company_only";

export interface MeetingOpportunityOption {
  id: number;
  title: string;
  stage_name: string;
  value: string | null;
  currency: string;
}

export interface Meeting extends Activity {
  /** Stan transkryptu Teams; `null` — spotkanie poza kolejką (gość, historia, Atlas). */
  transcript_status: "waiting" | "fetched" | "missing" | "not_online" | "forbidden" | "error" | null;
  transcript_summary: string | null;
  /** Co handlowiec ma zrobić z tym spotkaniem (kolumna „Co dalej”). */
  decision: MeetingDecision;
  timing: "soon" | "past" | "later";
  can_unpin: boolean;
  /** Przypiął je automat, bo firma miała jedną otwartą szansę; „Cofnij” odpina na stałe. */
  auto_pinned?: boolean;
  open_opportunities: MeetingOpportunityOption[];
  client_name: string | null;
  delivery_lead: string | null;
}

export interface MeetingList {
  items: Meeting[];
  total: number;
  counts: { pin: number; create: number; upcoming: number };
}

export interface MeetingTranscript {
  subject: string | null;
  summary: string | null;
  plain_text: string;
}

export interface ClientMailRecipient {
  address: string;
  name: string | null;
  /** Adres z bazy kandydatów: podsumowań z Sprzedaży tam nie wysyłamy. */
  blocked: "candidate" | null;
}

export interface ClientMailDraft {
  subject: string;
  body: string;
  /** Model nie dał szkicu: pole zostaje puste do napisania ręcznie. */
  model_failed: boolean;
  recipients: ClientMailRecipient[];
  mailbox: "ok" | "missing" | "no_send_scope";
  sender_address: string | null;
  sent_at: string | null;
}

export interface ClientMailSendInput {
  activityId: number;
  subject: string;
  body: string;
  to: string[];
  request_id: string;
  opportunity_id?: number | null;
}

export interface MeetingDraft {
  company: Ref;
  occurred_at: string | null;
  duration_minutes: number | null;
  suggested_title: string;
  attendees_known: boolean;
  people: { id: number; name: string; title: string | null; attended: boolean }[];
}

export interface MeetingFilters {
  q?: string;
  linked?: "opportunity" | "company";
  has_transcript?: boolean;
  date_from?: string;
  date_to?: string;
  mine?: boolean;
  queue?: "pin" | "create";
  upcoming?: boolean;
  limit?: number;
  offset?: number;
}

export function useSalesMeetings(filters: MeetingFilters) {
  return useQuery({
    queryKey: ["sales", "meetings", filters] as const,
    queryFn: async () =>
      (await api.get<MeetingList>("/api/sales/activities/meetings", { params: clean({ ...filters }) }))
        .data,
    placeholderData: keepPreviousData,
  });
}

export function useMeetingDraft(activityId: number) {
  return useQuery({
    queryKey: ["sales", "meetings", activityId, "draft"] as const,
    queryFn: async () =>
      (await api.get<MeetingDraft>(`/api/sales/activities/${activityId}/opportunity-draft`)).data,
  });
}

export function usePinActivity() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: { activityId: number; opportunityId: number }) =>
      (
        await api.post<Activity>(`/api/sales/activities/${input.activityId}/pin`, {
          opportunity_id: input.opportunityId,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useUnpinActivity() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (activityId: number) =>
      (await api.delete<Activity>(`/api/sales/activities/${activityId}/pin`)).data,
    onSuccess: invalidate,
  });
}

export function useCreateOpportunityFromMeeting() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (input: {
      activityId: number;
      title: string;
      service_line: ServiceLine;
      contact_ids: number[];
    }) => {
      const { activityId, ...payload } = input;
      return (await api.post<{ id: number; title: string }>(`/api/sales/opportunities/from-activity/${activityId}`, payload))
        .data;
    },
    onSuccess: invalidate,
  });
}

export function useMeetingTranscript(activityId: number | null) {
  return useQuery({
    queryKey: ["sales", "meetings", activityId, "transcript"] as const,
    queryFn: async () =>
      (await api.get<MeetingTranscript>(`/api/sales/activities/${activityId}/transcript`)).data,
    enabled: activityId !== null,
  });
}

export function useClientMailDraft(activityId: number) {
  return useQuery({
    queryKey: ["sales", "meetings", activityId, "client-summary"] as const,
    queryFn: async () =>
      (await api.get<ClientMailDraft>(`/api/sales/activities/${activityId}/client-summary`)).data,
    // Szkic modelu powstaje raz i leży przy transkrypcie; bez ponowień po błędzie.
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function useSendClientMail() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async ({ activityId, ...payload }: ClientMailSendInput) =>
      (await api.post<Activity>(`/api/sales/activities/${activityId}/client-summary/send`, payload)).data,
    onSuccess: invalidate,
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

export type LeadSource = "job_board" | "linkedin" | "press" | "manual" | "atlas" | "research";
export type LeadStatus = "new" | "contacted" | "converted" | "dismissed";

export const LEAD_SOURCE_LABELS: Record<LeadSource, string> = {
  job_board: "Ogłoszenia",
  linkedin: "LinkedIn",
  press: "Prasa",
  manual: "Ręcznie",
  atlas: "Z Atlasa",
  research: "Bot Leady",
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
  /** Osoba przypisana i czy pracuje w Sprzedaży (aktywna, z uprawnieniem Sprzedaży). */
  assignee?: Ref | null;
  assignee_in_sales?: boolean;
  /** Teczka firmy leada z danych NEXUSA; `null`, gdy lead nie ma karty albo karta jest pusta. */
  dossier?: LeadDossier | null;
}

/** Co NEXUS wie o firmie leada: karta, kogo znamy, decydenci, punkty do rozmowy. */
export interface LeadDossier {
  company_id: number;
  industry: string | null;
  city: string | null;
  nip: string | null;
  /** Domena karty albo host strony www (bez `www.`). */
  website: string | null;
  known: number;
  known_with_email: number;
  owner: string | null;
  /** Do 4 stanowisk decyzyjnych z kontaktów karty. */
  decision_makers: string[];
  points: number;
  points_at: string | null;
}

export interface LeadList {
  items: Lead[];
  total: number;
  counts: Record<LeadStatus, number>;
  /** Kanał sygnałów z bota researchu włączony (flaga po stronie serwera). */
  signals_enabled?: boolean;
  /** Zadania bota poza sygnałami („Warto wrócić”, „Nowe centra IT”), `SALES_BOT_TASKS_ENABLED`. */
  bot_tasks_enabled?: boolean;
}

export interface LeadFilters {
  status: LeadStatus;
  source?: LeadSource | "";
  q?: string;
  company_id?: number;
  /** Wszystkie statusy naraz (skrzynka sygnałów grupuje sama); `status` wtedy nie filtruje. */
  all_statuses?: boolean;
  limit?: number;
  /** Pochodzenie leada z bota (`payload.origin`): `grok` sygnały, `winback` „Warto wrócić”. */
  origin?: "grok" | "winback";
}

export function useLeads(filters: LeadFilters, enabled = true) {
  return useQuery({
    queryKey: ["sales", "leads", filters] as const,
    queryFn: async () =>
      (await api.get<LeadList>("/api/sales/leads", { params: clean({ ...filters }) })).data,
    enabled,
  });
}

// ── Sygnały z bota researchu (Grok Bot) ─────────────────────────────────

export type SignalStrength = "strong" | "medium" | "weak";
export type SignalType =
  | "hiring"
  | "restructuring"
  | "program"
  | "contract"
  | "investment"
  | "leadership"
  | "other";

export const SIGNAL_STRENGTH_LABELS: Record<SignalStrength, string> = {
  strong: "Silny",
  medium: "Średni",
  weak: "Słaby",
};
export const SIGNAL_TYPE_LABELS: Record<SignalType, string> = {
  hiring: "Zatrudnianie",
  restructuring: "Restrukturyzacja",
  program: "Program",
  contract: "Kontrakt",
  investment: "Inwestycja",
  leadership: "Zmiana zarządu",
  other: "Inne",
};

/** Pola sygnału zapisane przez serwer w `payload` leada z bota. */
export interface SignalPayload {
  type?: SignalType;
  strength?: SignalStrength;
  why_now?: string;
  published?: string;
  domain?: string;
}

export function signalPayload(lead: Pick<Lead, "payload">): SignalPayload {
  const raw = lead.payload ?? {};
  const text = (key: string) => (typeof raw[key] === "string" ? (raw[key] as string) : undefined);
  const strength = text("strength");
  const type = text("type");
  return {
    strength: strength && strength in SIGNAL_STRENGTH_LABELS ? (strength as SignalStrength) : undefined,
    type: type && type in SIGNAL_TYPE_LABELS ? (type as SignalType) : undefined,
    why_now: text("why_now"),
    published: text("published"),
    domain: text("domain"),
  };
}

export interface SignalRunReport {
  checked_firms?: number;
  sent_firms?: number;
  signals_in?: number;
  leads?: number;
  leads_new?: number;
  by_strength?: Partial<Record<SignalStrength, number>>;
  briefings?: number;
  quiet?: string[];
  dropped?: {
    outside_window?: { company: string; title: string; published: string }[];
    nexus_clients?: { company: string; client: string; delivery_lead: string | null }[];
    unknown_company?: number;
    duplicates?: number;
  };
}

export type SignalRunKind = "signals" | "briefing" | "winback" | "discovery";

export interface SignalRun {
  id: number;
  kind: SignalRunKind;
  status: "started" | "received" | "expired" | "failed";
  started_at: string;
  received_at: string | null;
  company_count: number;
  report: SignalRunReport;
  error: string | null;
}

export interface LatestSignalRun {
  enabled: boolean;
  reject_reasons: string[];
  run: SignalRun | null;
}

export function useLatestSignalRun(kind: SignalRunKind = "signals", enabled = true) {
  return useQuery({
    queryKey: ["sales", "signals", "latest-run", kind] as const,
    queryFn: async () =>
      (await api.get<LatestSignalRun>("/api/sales/signals/latest-run", { params: { kind } })).data,
    enabled,
  });
}

export interface TalkingPoint {
  text: string;
  url: string | null;
  published: string | null;
}

/** Haczyk przed telefonem z bota: zdanie otwarcia i do dwóch faktów ze źródłem. */
export interface CallHook {
  sentence: string;
  facts: { text: string; url: string; published: string }[];
  generated_at: string;
}

export interface CompanyBriefing {
  enabled: boolean;
  briefing: {
    mode: "first_call" | "ongoing" | "meeting_prep";
    points: TalkingPoint[];
    generated_at: string;
  } | null;
  /** Tylko przy włączonych zadaniach bota (`SALES_BOT_TASKS_ENABLED`). */
  call_hook?: CallHook | null;
}

export function useCompanyBriefing(companyId: number | null | undefined) {
  const id = companyId ?? 0;
  return useQuery({
    queryKey: ["sales", "signals", "briefing", id] as const,
    queryFn: async () =>
      (await api.get<CompanyBriefing>(`/api/sales/signals/briefings/${id}`)).data,
    enabled: Number.isFinite(id) && id > 0,
    staleTime: 5 * 60 * 1000,
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

/** „Przejmij”: lead bez osoby w Sprzedaży przechodzi na zalogowaną osobę (409, gdy ma). */
export function useTakeOverLead() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (id: number) => (await api.post<Lead>(`/api/sales/leads/${id}/take-over`, {})).data,
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

const OWNER_CANDIDATES_STALE_MS = 5 * 60_000;

/** Aktywne konta z uprawnieniem „Sprzedaż: edycja”. */
export function useOwnerCandidates(enabled = true) {
  return useQuery({
    queryKey: salesKeys.ownerCandidates,
    queryFn: async () => (await api.get<Ref[]>("/api/sales/opportunities/owner-candidates")).data,
    staleTime: OWNER_CANDIDATES_STALE_MS,
    enabled,
  });
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

// ── KPI tygodniowe i cele handlowców (decyzja Artura 28.10.2026, bez Ofert) ──

export type KpiMetric = "meetings" | "qualified" | "offers_stage";
export type KpiLight = "green" | "yellow" | "red";

export interface KpiCell {
  actual: number;
  target: number;
  light: KpiLight | null;
}

export interface SalesKpiPerson {
  user_id: number;
  name: string;
  team: string | null;
  has_targets: boolean;
  targets: Record<KpiMetric, number>;
  weeks: Record<KpiMetric, KpiCell>[];
  margin_goal_amount: string | null;
  margin_goal_deadline: string | null;
  margin_actual: string;
}

export interface SalesKpi {
  weeks: { start: string; iso_year: number; iso_week: number }[];
  people: SalesKpiPerson[];
  company: {
    net_mrr_goal: string | null;
    goal_deadline: string | null;
    won_net_mrr: string;
    missing_margin: number;
    months: { month: string; net_mrr: string; cum_net_mrr: string }[];
  };
  offers_history_since: string | null;
}

export interface SalesPersonTarget {
  user_id: number;
  name: string;
  is_active: boolean;
  has_targets: boolean;
  meetings: number;
  qualified: number;
  offers_stage: number;
  margin_goal_amount: string | null;
  margin_goal_deadline: string | null;
  team: string | null;
}

export interface SalesCompanyTarget {
  net_mrr_goal: string | null;
  goal_deadline: string | null;
}

export interface SalesTargets {
  company: SalesCompanyTarget;
  people: SalesPersonTarget[];
}

export type SalesPersonTargetInput = Pick<
  SalesPersonTarget,
  "meetings" | "qualified" | "offers_stage" | "margin_goal_amount" | "margin_goal_deadline" | "team"
>;

export function useSalesKpi(weeks = 8) {
  return useQuery({
    queryKey: ["sales", "kpi", weeks] as const,
    queryFn: async () => (await api.get<SalesKpi>("/api/sales/kpi", { params: { weeks } })).data,
  });
}

export function useSalesTargets(enabled = true) {
  return useQuery({
    queryKey: ["sales", "kpi-targets"] as const,
    queryFn: async () => (await api.get<SalesTargets>("/api/sales/kpi/targets")).data,
    enabled,
  });
}

export function useSetPersonTarget() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async ({ userId, ...body }: SalesPersonTargetInput & { userId: number }) =>
      (await api.put<SalesPersonTarget>(`/api/sales/kpi/targets/${userId}`, body)).data,
    onSuccess: invalidate,
  });
}

export function useSetCompanyTarget() {
  const invalidate = useInvalidateSales();
  return useMutation({
    mutationFn: async (body: SalesCompanyTarget) =>
      (await api.put<SalesCompanyTarget>("/api/sales/kpi/targets/company", body)).data,
    onSuccess: invalidate,
  });
}
