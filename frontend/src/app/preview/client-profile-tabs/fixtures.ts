/**
 * Dane harnessu `/preview/client-profile-tabs` — fikcyjny klient
 * „Bank Przykładowy S.A.” i wszystko, co pokazują zakładki jego profilu.
 *
 * Osoby, firma, numery umów i zamówień oraz kwoty są zmyślone (repo jest
 * publiczne). Daty „za N dni” liczą się od dziś, więc plakietki terminów nie
 * starzeją się razem z plikiem.
 *
 * Kształty bez eksportowanego typu (kontakty, wiedza, materiały, cennik,
 * projekty, statystyki współpracy) są lustrem interfejsów lokalnych
 * w `app/clients/[id]/page.tsx`, `MaterialsTab.tsx`, `ProjectsTab.tsx`
 * i `components/RateCardsTab.tsx`.
 */

import type {
  ClientTeamResponse,
  CompetenceCategoryOut,
  ConflictRegistryList,
  ConflictRegistryRow,
} from "@/lib/api";
import type {
  AmendmentRead,
  ClientDashboardResponse,
  ClientOrderRead,
  ClientOrdersGroupedResponse,
  ContractWithOrdersRead,
  FrameworkContractListResponse,
  FrameworkContractRead,
} from "@/lib/api/dlPortal";
import type {
  ClientMdImportDetail,
  ClientMdImportRow,
  ClientMdImportSummary,
  OrderGroupListResponse,
} from "@/lib/api/orderGroups";
import type { ClientPlaybook, PlaybookEvent } from "@/lib/client-playbooks";
import type { ClientCvRule } from "@/lib/cv-rules";
import type { JobRecruiter } from "@/lib/job-team";
import type { User } from "@/store/auth";
import { makeCvRule } from "@/test/fixtures/cv-rule";
import type {
  ActiveConsultantItem,
  ClientProfileResponse,
  HistoricalPlacementItem,
} from "@/types/client-profile";

export const CLIENT_ID = 9001;
export const CLIENT_NAME = "Bank Przykładowy S.A.";

/** Miesiąc roboczy NEXUSA: 168 h (21 MD × 8 h). */
const HOURS_PER_MONTH = 168;

/** Fikcyjny admin z finansami — widać kwoty i wszystkie akcje. */
export const PREVIEW_USER: User = {
  id: 1,
  email: "preview@example.com",
  name: "Administrator Przykładowy",
  role: "admin",
  roles: ["admin"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  capabilities: ["view_finance", "manage_finance"],
  analytics_capabilities: ["view_finance", "manage_finance"],
};

/** Data lokalna przesunięta o `days` dni. */
function isoOffset(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** „RRRR-MM” miesiąca przesuniętego o `months` względem bieżącego. */
function monthOffset(months: number): { iso: string; label: string } {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() + months);
  const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  const label = new Intl.DateTimeFormat("pl-PL", {
    month: "short",
    year: "numeric",
  }).format(d);
  return { iso, label };
}

// ── Klient i zespół ─────────────────────────────────────────────────────────

export const CLIENT = {
  id: CLIENT_ID,
  name: CLIENT_NAME,
  display_name: null,
  status: "active",
  industry: "Bankowość",
  website: "bank-przykladowy.example",
  address: "ul. Fikcyjna 1, 00-001 Warszawa",
  nda_signed: true,
  contract_type: "b2b",
  notes:
    "Klient strategiczny od 2024 r. Zamówienia przychodzą raz na kwartał, " +
    "decyzje o przedłużeniach zapadają na komitecie w pierwszym tygodniu miesiąca.",
  legacy_null_order_type: "periodic",
};

export const TEAM: ClientTeamResponse = {
  tacs: [],
  delivery_leads: [
    {
      id: 71,
      user_id: 11,
      name: "Marta Liderska",
      email: "marta.liderska@firma.example",
      role: "delivery_lead",
      created_at: "2024-03-04T09:00:00Z",
      is_head: true,
    },
    {
      id: 72,
      user_id: 12,
      name: "Norbert Zastępczy",
      email: "norbert.zastepczy@firma.example",
      role: "delivery_lead",
      created_at: "2025-06-16T09:00:00Z",
      is_head: false,
    },
    {
      id: 73,
      user_id: 13,
      name: "Olga Wspierająca",
      email: "olga.wspierajaca@firma.example",
      role: "delivery_lead",
      created_at: "2026-02-02T09:00:00Z",
      is_head: false,
    },
  ],
};

/** `GET /api/users` — kandydaci do pola „Dodaj Delivery Leada”. */
export const USERS = [
  { id: 1, name: "Administrator Przykładowy", email: "preview@example.com", role: "admin", is_active: true },
  { id: 11, name: "Marta Liderska", email: "marta.liderska@firma.example", role: "delivery_lead", is_active: true },
  { id: 12, name: "Norbert Zastępczy", email: "norbert.zastepczy@firma.example", role: "delivery_lead", is_active: true },
  { id: 13, name: "Olga Wspierająca", email: "olga.wspierajaca@firma.example", role: "delivery_lead", is_active: true },
  { id: 14, name: "Patryk Dodatkowy", email: "patryk.dodatkowy@firma.example", role: "delivery_lead", is_active: true },
  { id: 15, name: "Róża Nadzorująca", email: "roza.nadzorujaca@firma.example", role: "head_of_recruitment", is_active: true },
];

export const COMPETENCE_CATEGORIES: CompetenceCategoryOut[] = [
  { id: 1, slug: "infrastructure_operations", name_pl: "Infra & Operations & Security / Data & AI", name_en: "Infra & Operations", description: "", keywords: [], display_order: 1 },
  { id: 2, slug: "software_development", name_pl: "Development", name_en: "Development", description: "", keywords: [], display_order: 2 },
  { id: 3, slug: "security_quality", name_pl: "QA", name_en: "QA", description: "", keywords: [], display_order: 3 },
  { id: 4, slug: "management_delivery", name_pl: "Management & Delivery (PM & BA)", name_en: "Management & Delivery", description: "", keywords: [], display_order: 4 },
];

// ── Profil: konsultanci ─────────────────────────────────────────────────────

interface ConsultantSeed {
  contractId: number;
  candidateId: number;
  name: string;
  category: string;
  jobId: number;
  jobTitle: string;
  start: string;
  costPerHour: number;
  revenuePerHour: number;
  /** Koniec umowy za N dni; brak = umowa bezterminowa. */
  endsInDays?: number;
  jobFromOrder?: boolean;
}

const ACTIVE_SEEDS: ConsultantSeed[] = [
  { contractId: 8101, candidateId: 5101, name: "Anna Przykładowa", category: "management_delivery", jobId: 6101, jobTitle: "Analityk biznesowy — bankowość detaliczna", start: "2025-03-03", costPerHour: 120, revenuePerHour: 155 },
  { contractId: 8102, candidateId: 5102, name: "Bartosz Wzorcowy", category: "software_development", jobId: 6102, jobTitle: "Java Developer — system kredytowy", start: "2025-06-02", costPerHour: 150, revenuePerHour: 190, endsInDays: 21 },
  { contractId: 8103, candidateId: 5103, name: "Celina Testowa", category: "security_quality", jobId: 6103, jobTitle: "Tester automatyzujący", start: "2025-09-01", costPerHour: 95, revenuePerHour: 125 },
  { contractId: 8104, candidateId: 5104, name: "Dariusz Makietowy", category: "infrastructure_operations", jobId: 6104, jobTitle: "DevOps Engineer", start: "2026-01-12", costPerHour: 160, revenuePerHour: 205, jobFromOrder: true },
  { contractId: 8105, candidateId: 5105, name: "Ewa Fikcyjna", category: "management_delivery", jobId: 6105, jobTitle: "Scrum Master", start: "2026-02-02", costPerHour: 130, revenuePerHour: 160, endsInDays: 64 },
  { contractId: 8106, candidateId: 5106, name: "Filip Demonstracyjny", category: "software_development", jobId: 6102, jobTitle: "Frontend Developer — bankowość internetowa", start: "2026-04-01", costPerHour: 140, revenuePerHour: 178 },
];

function activeConsultant(seed: ConsultantSeed): ActiveConsultantItem {
  const margin = (seed.revenuePerHour - seed.costPerHour) * HOURS_PER_MONTH;
  return {
    contract_id: seed.contractId,
    candidate: {
      id: seed.candidateId,
      name: seed.name,
      avatar_url: null,
      competence_category: seed.category,
      linkedin: null,
    },
    job_id: seed.jobId,
    job_title: seed.jobTitle,
    job_from_order: seed.jobFromOrder ?? false,
    start_date: seed.start,
    end_date: seed.endsInDays == null ? null : isoOffset(seed.endsInDays),
    days_to_end: seed.endsInDays ?? null,
    contract_status: seed.endsInDays != null && seed.endsInDays <= 30 ? "ending" : "active",
    monthly_rate_client: seed.revenuePerHour * HOURS_PER_MONTH,
    monthly_rate_candidate: seed.costPerHour * HOURS_PER_MONTH,
    monthly_margin: margin,
    hourly_rate_client: seed.revenuePerHour,
    hourly_rate_candidate: seed.costPerHour,
    currency: "PLN",
    project_part: null,
    executive_contract: null,
  };
}

function archivedPlacement(
  overrides: Partial<HistoricalPlacementItem> & Pick<HistoricalPlacementItem, "contract_id">,
): HistoricalPlacementItem {
  return {
    candidate: {
      id: 5201,
      name: "Henryk Archiwalny",
      avatar_url: null,
      competence_category: "software_development",
      linkedin: null,
    },
    job_id: 6090,
    job_title: "Backend Developer — hurtownia danych",
    job_from_order: false,
    start_date: "2024-04-01",
    end_date: "2025-12-31",
    terminated_at: null,
    termination_reason: "project_ended",
    duration_months: 21,
    monthly_rate_client: 29_400,
    monthly_rate_candidate: 23_520,
    monthly_margin: 5_880,
    hourly_rate_client: 175,
    hourly_rate_candidate: 140,
    total_revenue: 617_400,
    ...overrides,
  };
}

function profile(): ClientProfileResponse {
  const active = ACTIVE_SEEDS.map(activeConsultant);
  const planned = activeConsultant({
    contractId: 8107,
    candidateId: 5107,
    name: "Grażyna Planowana",
    category: "infrastructure_operations",
    jobId: 6104,
    jobTitle: "Data Engineer — raportowanie nadzorcze",
    start: isoOffset(14),
    costPerHour: 155,
    revenuePerHour: 198,
  });
  return {
    summary: {
      open_jobs: 4,
      active_consultants: active.length,
      active_contracts: active.length,
      total_placements: 14,
      active_mrr: active.reduce((sum, row) => sum + (row.monthly_margin ?? 0), 0),
      active_mrr_unpriced_contracts: 0,
      active_mrr_fx_missing_contracts: 0,
      ltv: 1_284_000,
      avg_time_to_fill_days: 23,
      avg_time_to_fill_source: "opened_at",
      avg_time_to_fill_not_assessable: 0,
    },
    open_jobs: [],
    active_consultants: active,
    planned_consultants: [planned],
    historical: {
      placements: [
        archivedPlacement({ contract_id: 8001 }),
        archivedPlacement({
          contract_id: 8002,
          candidate: { id: 5202, name: "Iwona Zakończona", avatar_url: null, competence_category: "security_quality", linkedin: null },
          job_id: 6091,
          job_title: "Testerka manualna — aplikacja mobilna",
          start_date: "2024-09-02",
          end_date: "2025-08-29",
          termination_reason: "consultant_resigned",
          duration_months: 12,
          monthly_rate_client: 20_160,
          monthly_rate_candidate: 15_960,
          monthly_margin: 4_200,
          hourly_rate_client: 120,
          hourly_rate_candidate: 95,
          total_revenue: 241_920,
        }),
        archivedPlacement({
          contract_id: 8003,
          candidate: { id: 5203, name: "Jakub Dawny", avatar_url: null, competence_category: "management_delivery", linkedin: null },
          job_id: null,
          job_title: "Project Manager — migracja systemu centralnego",
          start_date: "2024-03-04",
          end_date: "2025-02-28",
          termination_reason: "client_budget_cut",
          duration_months: 12,
          monthly_rate_client: 31_920,
          monthly_rate_candidate: 26_040,
          monthly_margin: 5_880,
          hourly_rate_client: 190,
          hourly_rate_candidate: 155,
          total_revenue: 383_040,
        }),
      ],
      placements_total: 8,
      lost_jobs: [],
    },
  };
}

// ── Profil: statystyki, materiały, konflikty ────────────────────────────────

function coopTrend() {
  const ratios = [33.3, 50, 0, 40, 66.7, 50];
  const counts: Array<[number, number]> = [[1, 3], [1, 2], [0, 1], [2, 5], [2, 3], [1, 2]];
  return {
    client_id: CLIENT_ID,
    months: 6,
    trend: ratios.map((hit_ratio, index) => {
      const month = monthOffset(index - 5);
      return {
        month: month.iso,
        month_label: month.label,
        filled_jobs: counts[index][0],
        closed_jobs: counts[index][1],
        hit_ratio,
      };
    }),
  };
}

const COOP_STATS = {
  clients: [
    {
      client_id: CLIENT_ID,
      closed_jobs: 16,
      filled_jobs: 7,
      placements: 9,
      total_vacancies: 20,
      hit_ratio: 43.8,
      fill_rate: 45,
      fill_rate_source: "headcount",
      active_jobs: 4,
      target_achieved: true,
      outcome_coverage_pct: 87.5,
    },
  ],
  overall: { hit_ratio_target_pct: 30 },
};

const ONE_PAGERS = [
  {
    id: 401,
    client_id: CLIENT_ID,
    title: "Oferta zespołów IT dla sektora bankowego",
    description: "Wersja na rozmowy z działem zakupów.",
    version: "3",
    filename: "Oferta_zespoly_IT_bankowosc.pdf",
    content_type: "application/pdf",
    size_bytes: 1_245_000,
    uploaded_by: 11,
    uploaded_by_email: "marta.liderska@firma.example",
    created_at: "2026-06-12T10:15:00Z",
  },
  {
    id: 402,
    client_id: CLIENT_ID,
    title: "Profile konsultantów — testy automatyczne",
    description: null,
    version: "1",
    filename: "Profile_QA_automatyzacja.docx",
    content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    size_bytes: 384_000,
    uploaded_by: 12,
    uploaded_by_email: "norbert.zastepczy@firma.example",
    created_at: "2026-08-21T08:40:00Z",
  },
];

const REQUIRED_DOC_TEMPLATES = [
  { id: 1, name: "NDA", description: "Umowa o zachowaniu poufności", is_default: true, sort_order: 1 },
  { id: 2, name: "Klauzula RODO", description: "Powierzenie przetwarzania danych", is_default: true, sort_order: 2 },
  { id: 3, name: "Oświadczenie o braku konfliktu interesów", description: null, is_default: false, sort_order: 3 },
  { id: 4, name: "Polisa OC wykonawcy", description: null, is_default: false, sort_order: 4 },
];

const REQUIRED_DOCS = [
  {
    id: 501, client_id: CLIENT_ID, template_id: 1, name: "NDA", description: "Umowa o zachowaniu poufności",
    is_mandatory: true, status: "signed", filename: "NDA_Bank_Przykladowy.pdf", content_type: "application/pdf",
    size_bytes: 212_000, uploaded_by: 11, uploaded_by_email: "marta.liderska@firma.example",
    uploaded_at: "2024-03-01T12:00:00Z", notes: null, created_at: "2024-02-20T09:00:00Z", updated_at: "2024-03-01T12:00:00Z",
  },
  {
    id: 502, client_id: CLIENT_ID, template_id: 2, name: "Klauzula RODO", description: "Powierzenie przetwarzania danych",
    is_mandatory: true, status: "uploaded", filename: "Powierzenie_danych_projekt.pdf", content_type: "application/pdf",
    size_bytes: 148_000, uploaded_by: 12, uploaded_by_email: "norbert.zastepczy@firma.example",
    uploaded_at: "2026-09-18T14:30:00Z", notes: "Czeka na podpis po stronie banku.", created_at: "2024-02-20T09:00:00Z", updated_at: "2026-09-18T14:30:00Z",
  },
  {
    id: 503, client_id: CLIENT_ID, template_id: 3, name: "Oświadczenie o braku konfliktu interesów", description: null,
    is_mandatory: true, status: "pending", filename: null, content_type: null,
    size_bytes: null, uploaded_by: null, uploaded_by_email: null,
    uploaded_at: null, notes: null, created_at: "2026-05-05T09:00:00Z", updated_at: "2026-05-05T09:00:00Z",
  },
  {
    id: 504, client_id: CLIENT_ID, template_id: 4, name: "Polisa OC wykonawcy", description: null,
    is_mandatory: false, status: "n_a", filename: null, content_type: null,
    size_bytes: null, uploaded_by: null, uploaded_by_email: null,
    uploaded_at: null, notes: "Klient nie wymaga przy stawkach godzinowych.", created_at: "2026-05-05T09:00:00Z", updated_at: "2026-05-05T09:00:00Z",
  },
];

const CONTRACT_TERMS = {
  id: 61,
  client_id: CLIENT_ID,
  internalization_fee_pct: "15",
  internalization_min_months: 12,
  internalization_notice_days: 60,
  internalization_notes: "Opłata liczona od rocznego wynagrodzenia konsultanta.",
  payment_net_days: 30,
  payment_currency: "PLN",
  payment_invoice_cycle: "monthly",
  payment_late_fees: "ustawowe",
  payment_notes: "Faktura do 5. dnia miesiąca, z zestawieniem godzin.",
  notice_period_days: 30,
  warranty_replacement_days: 14,
  warranty_notes: "Bezpłatna wymiana konsultanta w pierwszych 30 dniach.",
  other_clauses: "Zakaz podwykonawstwa bez zgody klienta.",
  updated_by_email: "marta.liderska@firma.example",
  updated_at: "2026-07-03T11:20:00Z",
};

function conflictRow(overrides: Partial<ConflictRegistryRow>): ConflictRegistryRow {
  return {
    id: 901,
    candidate_id: 5301,
    candidate_name: "Karol Zastrzeżony",
    client_id: CLIENT_ID,
    client_name: CLIENT_NAME,
    type: "blacklist",
    type_label: "Czarna lista klienta",
    reason: "Klient zakończył współpracę po okresie próbnym w 2025 r.",
    active: true,
    state: "active",
    expires_at: null,
    created_by: 11,
    created_by_name: "Marta Liderska",
    created_at: "2025-11-04T10:00:00Z",
    deactivated_at: null,
    deactivated_by: null,
    deactivated_by_name: null,
    deactivation_reason: null,
    ...overrides,
  };
}

function conflicts(): ConflictRegistryList {
  const items = [
    conflictRow({}),
    conflictRow({
      id: 902,
      candidate_id: 5302,
      candidate_name: "Lena Poufna",
      type: "nda",
      type_label: "NDA / cooling-off",
      reason: "Okres karencji po projekcie u dostawcy klienta.",
      expires_at: `${isoOffset(75)}T00:00:00Z`,
    }),
  ];
  return {
    items,
    total: items.length,
    limit: 100,
    offset: 0,
    type_labels: {
      blacklist: "Czarna lista klienta",
      nda: "NDA / cooling-off",
      competitor: "Klient konkurencyjny",
      current_employment: "Obecne zatrudnienie",
    },
  };
}

// ── Zasady współpracy ───────────────────────────────────────────────────────

const PLAYBOOK: ClientPlaybook = {
  client_id: CLIENT_ID,
  client_name: CLIENT_NAME,
  exists: true,
  version: 4,
  sla_business_days: 5,
  sla_min_candidates: 3,
  cv_limit_per_process: 4,
  hold_hours: 48,
  multi_project_cooldown_days: 90,
  rate_policy: "Stawki z cennika klienta; negocjacje tylko przed wysyłką CV.",
  about_for_candidate:
    "Duży bank detaliczny z własnym centrum IT w Warszawie. Zespoły produktowe " +
    "po 6–8 osób, praca hybrydowa (2 dni w biurze), dokumentacja po polsku.",
  about_for_candidate_origin: "manual",
  about_for_candidate_sources: [],
  priority_rules:
    "Najpierw kandydaci z doświadczeniem w bankowości. Osoby, które pracowały " +
    "już u tego klienta, zgłaszamy po potwierdzeniu u Delivery Leada.",
  process_rules_md:
    "## Etapy\n1. Rozmowa z hiring managerem (45 min)\n2. Zadanie techniczne na żywo\n3. Decyzja w 3 dni robocze\n\n" +
    "## Wysyłka CV\n- jedno CV na jedno zapytanie\n- stawka podana w treści zgłoszenia",
  onboarding_md:
    "## Po akceptacji\n- NDA i oświadczenia w 3 dni robocze\n- sprzęt od klienta, odbiór w biurze\n- dostęp do sieci po szkoleniu z bezpieczeństwa",
  documents: [
    { name: "Wzór NDA klienta", url: "https://intranet.example/dokumenty/nda-bank-przykladowy" },
    { name: "Instrukcja onboardingu", url: "https://intranet.example/dokumenty/onboarding-bank-przykladowy" },
  ],
  seed_key: null,
  updated_at: "2026-09-12T10:00:00Z",
  updated_by_name: "Marta Liderska",
};

const PLAYBOOK_HISTORY: PlaybookEvent[] = [
  {
    id: 2,
    playbook_version: 4,
    action: "saved",
    changes: { sla_business_days: { from: 7, to: 5 } },
    actor_name: "Marta Liderska",
    created_at: "2026-09-12T10:00:00Z",
  },
  {
    id: 1,
    playbook_version: 3,
    action: "saved",
    changes: { cv_limit_per_process: { from: 3, to: 4 } },
    actor_name: "Norbert Zastępczy",
    created_at: "2026-06-02T08:30:00Z",
  },
];

const CV_RULE: ClientCvRule = makeCvRule({
  client_id: CLIENT_ID,
  client_name: CLIENT_NAME,
  cv_language: "pl",
  confirmed_at: "2026-08-31T10:00:00Z",
  confirmed_by_name: "Marta Liderska",
  client_policy: "nazwa pliku, język PL",
  filename_preview: "B2B_Analityk biznesowy_Anna Przykładowa.docx",
});

// ── Projekty ────────────────────────────────────────────────────────────────

function recruiter(user_id: number, name: string, overrides: Partial<JobRecruiter> = {}): JobRecruiter {
  return { user_id, name, via: "owner", proposed: false, assigned_by_name: null, ...overrides };
}

const URSZULA = recruiter(21, "Urszula Rekrutująca");
const WIKTOR = recruiter(22, "Wiktor Wspierający", { via: "assignment", assigned_by_name: "Róża Nadzorująca" });
const ZOFIA = recruiter(23, "Zofia Wspomagająca", { via: "collaborator" });

const ACTIVE_JOBS = [
  { id: 6102, title: "Java Developer — system kredytowy", location: "Warszawa", status: "published", client_reference: "ZAP-2026-014", candidate_count: 18, opened_effective_at: isoOffset(-34), recruiters: [URSZULA, WIKTOR] },
  { id: 6104, title: "DevOps Engineer", location: "Warszawa, Gdańsk", status: "published", client_reference: "ZAP-2026-019", candidate_count: 9, opened_effective_at: isoOffset(-21), recruiters: [URSZULA] },
  { id: 6107, title: "Analityk danych — raportowanie nadzorcze", location: "zdalnie", status: "published", client_reference: null, candidate_count: 4, opened_effective_at: isoOffset(-9), recruiters: [] },
  { id: 6108, title: "Tester automatyzujący — bankowość mobilna", location: "Kraków", status: "published", client_reference: "ZAP-2026-023", candidate_count: 12, opened_effective_at: isoOffset(-5), recruiters: [WIKTOR, URSZULA, ZOFIA] },
  { id: 6109, title: "Architekt rozwiązań chmurowych", location: null, status: "draft", client_reference: null, candidate_count: 0, opened_effective_at: isoOffset(-1), recruiters: [] },
];

const CLOSED_JOBS = [
  { id: 6101, title: "Analityk biznesowy — bankowość detaliczna", location: "Warszawa", status: "closed", client_reference: "ZAP-2025-003", candidate_count: 27, opened_effective_at: "2025-01-13", recruiters: [URSZULA] },
  { id: 6103, title: "Tester automatyzujący", location: "Warszawa", status: "closed", client_reference: "ZAP-2025-021", candidate_count: 15, opened_effective_at: "2025-07-07", recruiters: [WIKTOR] },
  { id: 6105, title: "Scrum Master", location: "zdalnie", status: "closed", client_reference: null, candidate_count: 11, opened_effective_at: "2025-12-01", recruiters: [URSZULA] },
];

// ── Kontakty i wiedza ───────────────────────────────────────────────────────

const CONTACTS = [
  {
    id: 301, client_id: CLIENT_ID, name: "Paweł Decyzyjny", email: "pawel.decyzyjny@bank-przykladowy.example",
    phone: "+48 500 000 001", position: "Dyrektor IT", department: "Technologia", is_decision_maker: true,
    notes: "Zatwierdza budżety zespołów; spotkania najlepiej we wtorki.", last_contacted_at: isoOffset(-6),
    created_at: "2024-03-05T09:00:00Z", is_key_relationship: true, relationship_strength: "champion",
    relationship_notes: "Poleca nas innym departamentom banku.", key_relationship_owner_id: 11,
    last_personal_touchpoint_at: isoOffset(-6),
  },
  {
    id: 302, client_id: CLIENT_ID, name: "Renata Zakupowa", email: "renata.zakupowa@bank-przykladowy.example",
    phone: "+48 500 000 002", position: "IT Procurement Manager", department: "Zakupy", is_decision_maker: true,
    notes: null, last_contacted_at: isoOffset(-19), created_at: "2024-03-05T09:00:00Z",
    is_key_relationship: true, relationship_strength: "strong",
    relationship_notes: null, key_relationship_owner_id: 11, last_personal_touchpoint_at: isoOffset(-19),
  },
  {
    id: 303, client_id: CLIENT_ID, name: "Stefan Projektowy", email: "stefan.projektowy@bank-przykladowy.example",
    phone: "+48 500 000 003", position: "Kierownik projektu", department: "Kredyty", is_decision_maker: false,
    notes: "Hiring manager w zapytaniach o programistów Java.", last_contacted_at: isoOffset(-41),
    created_at: "2025-02-10T09:00:00Z", is_key_relationship: false, relationship_strength: "warm",
    relationship_notes: null, key_relationship_owner_id: null, last_personal_touchpoint_at: null,
  },
  {
    id: 304, client_id: CLIENT_ID, name: "Teresa Kadrowa", email: "teresa.kadrowa@bank-przykladowy.example",
    phone: null, position: "HR Business Partner", department: "HR", is_decision_maker: false,
    notes: null, last_contacted_at: null, created_at: "2026-01-20T09:00:00Z",
    is_key_relationship: false, relationship_strength: "cold",
    relationship_notes: null, key_relationship_owner_id: null, last_personal_touchpoint_at: null,
  },
];

const KNOWLEDGE = [
  { id: 201, client_id: CLIENT_ID, category: "selling_points", content: "Stabilne, wieloletnie projekty i jasna ścieżka przedłużeń — większość konsultantów zostaje ponad rok.", added_by: 11, source: "rozmowa z dyrektorem IT, 06.2026", created_at: "2026-06-18T09:00:00Z" },
  { id: 202, client_id: CLIENT_ID, category: "selling_points", content: "Nowoczesny stos w nowych projektach, budżet szkoleniowy także dla kontraktorów.", added_by: 12, source: null, created_at: "2026-04-02T09:00:00Z" },
  { id: 203, client_id: CLIENT_ID, category: "interview_questions", content: "Pytają o doświadczenie z systemami transakcyjnymi i o sposób pracy z długiem technicznym.\nZadanie na żywo trwa około 40 minut.", added_by: 12, source: "debrief po rozmowie, 08.2026", created_at: "2026-08-27T09:00:00Z" },
  { id: 204, client_id: CLIENT_ID, category: "tech_stack", content: "Java 21, Spring Boot, Kafka, Oracle, OpenShift. Front: React i TypeScript.", added_by: 11, source: null, created_at: "2026-03-11T09:00:00Z" },
  { id: 205, client_id: CLIENT_ID, category: "culture", content: "Praca hybrydowa, dwa dni w biurze. Zespoły mieszane — pracownicy banku i kontraktorzy przy jednym stole.", added_by: 13, source: "wizyta w biurze klienta", created_at: "2026-05-14T09:00:00Z" },
  { id: 206, client_id: CLIENT_ID, category: "general", content: "Zamrożenie zmian w grudniu — nowe osoby startują najwcześniej w drugim tygodniu stycznia.", added_by: 11, source: null, created_at: "2026-09-02T09:00:00Z" },
];

// ── Umowy ramowe i cennik ───────────────────────────────────────────────────

const FRAMEWORK_ACTIVE_ID = 7001;
const FRAMEWORK_PENDING_ID = 7002;

function frameworkContract(overrides: Partial<FrameworkContractRead>): FrameworkContractRead {
  return {
    id: FRAMEWORK_ACTIVE_ID,
    client_id: CLIENT_ID,
    name: "Umowa ramowa o świadczenie usług IT nr UR/2024/017",
    status: "active",
    effective_date: "2024-03-01",
    expiry_date: isoOffset(24),
    signed_via: "upload",
    currency: "PLN",
    parent_contract_id: null,
    contract_terms_id: 61,
    filename: "Umowa_ramowa_UR_2024_017.pdf",
    has_file: true,
    content_type: "application/pdf",
    size_bytes: 842_000,
    uploaded_by: 11,
    uploaded_at: "2024-03-01T12:00:00Z",
    notes: null,
    created_at: "2024-02-20T09:00:00Z",
    updated_at: "2026-07-01T09:00:00Z",
    amendments_count: 2,
    days_to_expiry: 24,
    ...overrides,
  };
}

function frameworkContracts(): FrameworkContractListResponse {
  const items = [
    frameworkContract({}),
    frameworkContract({
      id: FRAMEWORK_PENDING_ID,
      name: "Umowa ramowa — usługi testerskie 2027",
      status: "pending_signature",
      effective_date: isoOffset(45),
      expiry_date: null,
      filename: "Umowa_ramowa_testy_2027_projekt.pdf",
      size_bytes: 512_000,
      uploaded_by: 12,
      uploaded_at: "2026-09-25T10:00:00Z",
      created_at: "2026-09-25T10:00:00Z",
      updated_at: "2026-09-25T10:00:00Z",
      amendments_count: 0,
      days_to_expiry: null,
    }),
  ];
  return { items, total: items.length };
}

const AMENDMENTS: AmendmentRead[] = [
  {
    id: 7102,
    framework_contract_id: FRAMEWORK_ACTIVE_ID,
    name: "Aneks nr 2 — przedłużenie o 12 miesięcy",
    effective_date: "2026-01-01",
    changes_summary: "Nowy termin obowiązywania i waloryzacja stawek o 4%.",
    old_terms: null,
    new_terms: null,
    filename: "Aneks_2_UR_2024_017.pdf",
    has_file: true,
    content_type: "application/pdf",
    size_bytes: 164_000,
    uploaded_by: 11,
    uploaded_at: "2025-12-12T10:00:00Z",
    created_at: "2025-12-12T10:00:00Z",
    updated_at: "2025-12-12T10:00:00Z",
  },
  {
    id: 7101,
    framework_contract_id: FRAMEWORK_ACTIVE_ID,
    name: "Aneks nr 1 — termin płatności 30 dni",
    effective_date: "2025-01-01",
    changes_summary: "Skrócenie terminu płatności z 45 do 30 dni.",
    old_terms: null,
    new_terms: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    uploaded_by: null,
    uploaded_at: null,
    created_at: "2024-12-10T10:00:00Z",
    updated_at: "2024-12-10T10:00:00Z",
  },
];

const RATE_CARDS = [
  { id: 1101, client_id: CLIENT_ID, role: "Java Developer", seniority: "senior", rate_candidate_min: 140, rate_candidate_max: 165, rate_client_min: 180, rate_client_max: 205, currency: "PLN", rate_unit: "hourly", valid_from: "2026-01-01", valid_to: "2026-12-31", notes: "Stawki po waloryzacji z aneksu nr 2." },
  { id: 1102, client_id: CLIENT_ID, role: "Tester automatyzujący", seniority: "mid", rate_candidate_min: 90, rate_candidate_max: 110, rate_client_min: 120, rate_client_max: 140, currency: "PLN", rate_unit: "hourly", valid_from: "2026-01-01", valid_to: "2026-12-31", notes: null },
  { id: 1103, client_id: CLIENT_ID, role: "DevOps Engineer", seniority: "senior", rate_candidate_min: 1200, rate_candidate_max: 1360, rate_client_min: 1560, rate_client_max: 1720, currency: "PLN", rate_unit: "daily", valid_from: "2026-01-01", valid_to: null, notes: "Rozliczenie w MD." },
  { id: 1104, client_id: CLIENT_ID, role: "Analityk biznesowy", seniority: null, rate_candidate_min: 18_500, rate_candidate_max: 18_500, rate_client_min: null, rate_client_max: 26_000, currency: "PLN", rate_unit: "monthly", valid_from: null, valid_to: null, notes: null },
];

// ── Analityka ───────────────────────────────────────────────────────────────

function dashboard(activeMargin: number): ClientDashboardResponse {
  return {
    client_id: CLIENT_ID,
    client_name: CLIENT_NAME,
    total_revenue_all_time: "2846500.00",
    active_revenue: "612400.00",
    completed_revenue: "2234100.00",
    currency_breakdown: { PLN: "2654300.00", EUR: "192200.00" },
    monthly_margin_total: activeMargin,
    monthly_margin_pct: 21.5,
    active_consultants: ACTIVE_SEEDS.length,
    active_contracts: ACTIVE_SEEDS.length,
    completed_consultants: 8,
    avg_days_to_fill: 23,
    framework_contracts_count: 2,
    active_orders_count: ACTIVE_SEEDS.length,
    completed_orders_count: 19,
    // Te same terminy co w Profilu, Zamówieniach i Umowach.
    alerts: [
      { kind: "order", entity_id: 9102, label: "Zamówienie ZAM/2026/0412 — Bartosz Wzorcowy", days_to_expiry: 21, expiry_date: isoOffset(21) },
      { kind: "framework_contract", entity_id: FRAMEWORK_ACTIVE_ID, label: "Umowa ramowa UR/2024/017", days_to_expiry: 24, expiry_date: isoOffset(24) },
    ],
  };
}

/** Klucz cache Analityki — lustro `AnalyticsTab` (id, wersja autoryzacji,
 *  zakres danych i capability użytkownika). */
export function dashboardQueryKey(user: User): readonly unknown[] {
  const capabilityCacheKey = Array.from(
    new Set([...(user.capabilities ?? []), ...(user.analytics_capabilities ?? [])]),
  )
    .sort()
    .join(",");
  return [
    "client-dashboard",
    CLIENT_ID,
    user.id,
    user.authorization_version ?? null,
    "no-scope",
    capabilityCacheKey,
  ];
}

// ── Importy MD ──────────────────────────────────────────────────────────────

function importRow(overrides: Partial<ClientMdImportRow>): ClientMdImportRow {
  return {
    id: 1,
    row_number: 2,
    consultant_name: "Dariusz Makietowy",
    order_number_hint: "4599060011",
    target_order_number: "4599060011",
    target_group_id: 9201,
    md_reported: 20,
    invoice_amount: 32_800,
    state: "booked",
    state_label: "Zaksięgowano",
    status_label: "Dopasowano",
    status_reason: null,
    number_mismatch: false,
    ...overrides,
  };
}

function mdImports(): { list: ClientMdImportSummary[]; details: ClientMdImportDetail[] } {
  const latest: ClientMdImportSummary = {
    id: 3302,
    period_month: monthOffset(-1).iso,
    filename: "Zuzycie_MD_ostatni_miesiac.xlsx",
    created_at: `${isoOffset(-2)}T08:15:00Z`,
    uploaded_by_name: "Finanse Przykładowe",
    rows_total: 5,
    rows_booked: 2,
    rows_to_verify: 1,
    rows_error: 1,
    md_booked: 39,
  };
  const latestRows = [
    importRow({ id: 33021, row_number: 2 }),
    importRow({ id: 33022, row_number: 3, consultant_name: "Celina Testowa", md_reported: 19, invoice_amount: 19_000 }),
    importRow({
      id: 33023, row_number: 4, consultant_name: "Bartosz Wzorcowy", order_number_hint: "4599060019",
      target_order_number: null, target_group_id: null, md_reported: 21, invoice_amount: 31_920,
      state: "to_verify", state_label: "Do weryfikacji", status_label: "Wymaga przypisania",
      status_reason: "Osoba ma dwa zamówienia u tego klienta — wskaż właściwe w Finansach.", number_mismatch: true,
    }),
    importRow({
      id: 33024, row_number: 5, consultant_name: "Ewa Fikcyjna", order_number_hint: "4599060044",
      target_order_number: null, target_group_id: null, md_reported: 18, invoice_amount: null,
      state: "error", state_label: "Błąd", status_label: "Brak pasującego zamówienia",
      status_reason: "Zamówienia o tym numerze nie ma w NEXUSIE.",
    }),
    importRow({
      id: 33025, row_number: 6, consultant_name: "Anna Przykładowa", order_number_hint: null,
      target_order_number: null, target_group_id: null, md_reported: 21, invoice_amount: 26_040,
      state: "neutral", state_label: "Bez zamówienia MD", status_label: "Rozliczono kwotowo",
      status_reason: "Osoba pracuje na zamówieniu okresowym.",
    }),
  ];
  const previous: ClientMdImportSummary = {
    id: 3301,
    period_month: monthOffset(-2).iso,
    filename: "Zuzycie_MD_poprzedni_miesiac.xlsx",
    created_at: `${isoOffset(-33)}T09:40:00Z`,
    uploaded_by_name: null,
    rows_total: 3,
    rows_booked: 3,
    rows_to_verify: 0,
    rows_error: 0,
    md_booked: 61,
  };
  const previousRows = [
    importRow({ id: 33011, row_number: 2, md_reported: 21, invoice_amount: 34_440 }),
    importRow({ id: 33012, row_number: 3, consultant_name: "Celina Testowa", md_reported: 20, invoice_amount: 20_000 }),
    importRow({ id: 33013, row_number: 4, consultant_name: "Bartosz Wzorcowy", order_number_hint: "4599060012", target_order_number: "4599060012", target_group_id: 9202, md_reported: 20, invoice_amount: 30_400 }),
  ];
  return {
    list: [latest, previous],
    details: [
      { ...latest, rows: latestRows },
      { ...previous, rows: previousRows },
    ],
  };
}

// ── Zamówienia (minimalnie — pełny widok ma `/preview/client-orders`) ───────

function periodicOrder(seed: ConsultantSeed, index: number): ClientOrderRead {
  const end = isoOffset(seed.endsInDays ?? 120);
  return {
    id: 9101 + index,
    client_id: CLIENT_ID,
    contract_id: seed.contractId,
    job_id: seed.jobId,
    framework_contract_id: FRAMEWORK_ACTIVE_ID,
    title: `ZAM/2026/04${String(11 + index).padStart(2, "0")}`,
    description: null,
    status: "active",
    order_type: "periodic",
    start_date: isoOffset(-60),
    end_date: end,
    rate_unit: "hourly",
    billing_hours_per_month: HOURS_PER_MONTH,
    rate_candidate: seed.costPerHour,
    rate_client: seed.revenuePerHour,
    total_value: null,
    md_quantity: null,
    currency: "PLN",
    rate_client_currency: "PLN",
    rate_candidate_currency: "PLN",
    project_part: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    created_by_user_id: 11,
    notes: null,
    created_at: `${isoOffset(-62)}T09:00:00Z`,
    updated_at: `${isoOffset(-62)}T09:00:00Z`,
    candidate_id: seed.candidateId,
    candidate_name: seed.name,
    contract_status: "active",
    job_title: seed.jobTitle,
    monthly_margin: (seed.revenuePerHour - seed.costPerHour) * HOURS_PER_MONTH,
    days_to_end: seed.endsInDays ?? 120,
  };
}

function contractors(): ClientOrdersGroupedResponse {
  const rows: ContractWithOrdersRead[] = ACTIVE_SEEDS.map((seed, index) => {
    const order = periodicOrder(seed, index);
    return {
      contract_id: seed.contractId,
      candidate_id: seed.candidateId,
      candidate_name: seed.name,
      contract_status: "active",
      contract_start_date: seed.start,
      contract_end_date: null,
      rate_candidate: seed.costPerHour,
      rate_client_currency: "PLN",
      rate_candidate_currency: "PLN",
      rate_unit: "hourly",
      billing_hours_per_month: HOURS_PER_MONTH,
      initial_job_id: seed.jobId,
      initial_job_title: seed.jobTitle,
      latest_order_id: order.id,
      latest_order_end_date: order.end_date,
      latest_order_rate_client: seed.revenuePerHour,
      latest_order_monthly_margin: order.monthly_margin,
      days_to_latest_end: order.days_to_end,
      orders: [order],
    };
  });
  return { contractors: rows, total_contractors: rows.length, can_manage_finance: true };
}

const ORDER_GROUPS: OrderGroupListResponse = {
  groups: [],
  total_groups: 0,
  total_consultants: 0,
  suggested_order_type: "periodic",
};

// ── Komplet ─────────────────────────────────────────────────────────────────

export function buildFixtures() {
  const clientProfile = profile();
  return {
    client: CLIENT,
    team: TEAM,
    users: USERS,
    competenceCategories: COMPETENCE_CATEGORIES,
    profile: clientProfile,
    coopStats: COOP_STATS,
    coopTrend: coopTrend(),
    onePagers: ONE_PAGERS,
    requiredDocs: REQUIRED_DOCS,
    requiredDocTemplates: REQUIRED_DOC_TEMPLATES,
    contractTerms: CONTRACT_TERMS,
    conflicts: conflicts(),
    playbook: PLAYBOOK,
    playbookHistory: PLAYBOOK_HISTORY,
    cvRule: CV_RULE,
    activeJobs: { items: ACTIVE_JOBS, total: ACTIVE_JOBS.length },
    closedJobs: { items: CLOSED_JOBS, total: CLOSED_JOBS.length },
    contacts: CONTACTS,
    knowledge: KNOWLEDGE,
    frameworkContracts: frameworkContracts(),
    amendments: { [FRAMEWORK_ACTIVE_ID]: AMENDMENTS, [FRAMEWORK_PENDING_ID]: [] } as Record<number, AmendmentRead[]>,
    rateCards: RATE_CARDS,
    dashboard: dashboard(clientProfile.summary.active_mrr ?? 0),
    mdImports: mdImports(),
    orderGroups: ORDER_GROUPS,
    contractors: contractors(),
  };
}

export type ClientProfileFixtures = ReturnType<typeof buildFixtures>;
