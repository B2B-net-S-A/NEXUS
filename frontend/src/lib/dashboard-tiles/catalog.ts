// Katalog kafelków własnego pulpitu — jedno źródło prawdy po stronie frontu.
//
// Tu mieszka to, CO można dodać i KTO może to dodać. Jak kafelek się
// renderuje, rozstrzyga `components/v2/dashboard/custom/TileContent.tsx`.
// Typy muszą się zgadzać z `TileType` w backendzie
// (`backend/app/services/dashboard_tiles.py`) — pilnuje tego
// `test_dashboard_tile_types_mirror.py`.
//
// Reguły dostępu są lustrem bramek, które widżety miały na starym pulpicie
// (`RoleDashboard`): sekcja, a nie sama rola, bo backend odmawia 403 bez
// dostępu do sekcji, a seria kart błędu czytałaby się jak awaria pulpitu.
// Kafelki metryk nie mają tu reguł źródeł — o nich mówi serwerowy katalog
// (`/api/dashboard-metrics/catalog`).

import type {
  DashboardTile,
  MetricDefinition,
  TileConfig,
  TileType,
} from "@/lib/api/userDashboard";
import { hasCapability } from "@/lib/capabilities";
import { hasSectionAccess } from "@/lib/section-access";
import { getUserRoles, type User, type UserRole } from "@/store/auth";

export type TileCategory =
  | "my_work"
  | "recruitment"
  | "clients"
  | "finance"
  | "team"
  | "calendar"
  | "universal";

export const TILE_CATEGORY_LABELS: Record<TileCategory, string> = {
  my_work: "Moja praca",
  recruitment: "Rekrutacje",
  clients: "Klienci i zamówienia",
  finance: "Finanse",
  team: "Zespół",
  calendar: "Kalendarz",
  universal: "Uniwersalne",
};

export type TileAvailability = { ok: true } | { ok: false; reason: string };

type Size = { w: number; h: number };

export interface TileDefinition {
  type: TileType;
  label: string;
  description: string;
  category: TileCategory;
  defaultSize: Size;
  minSize: Size;
  /** Widżet ma własną kartę z nagłówkiem — ramka kafelka go nie dubluje. */
  ownChrome: boolean;
  availability: (user: User | null | undefined) => TileAvailability;
}

const ANY: TileDefinition["availability"] = () => ({ ok: true });

function needsSection(
  section: "pipeline" | "delivery" | "sourcing" | "insights",
  label: string,
): TileDefinition["availability"] {
  return (user) =>
    hasSectionAccess(user, section)
      ? { ok: true }
      : { ok: false, reason: `Wymaga dostępu do sekcji ${label}` };
}

function needsRole(
  roles: UserRole[],
  reason: string,
): TileDefinition["availability"] {
  return (user) =>
    getUserRoles(user).some((role) => roles.includes(role))
      ? { ok: true }
      : { ok: false, reason };
}

function both(
  ...checks: TileDefinition["availability"][]
): TileDefinition["availability"] {
  return (user) => {
    for (const check of checks) {
      const result = check(user);
      if (!result.ok) return result;
    }
    return { ok: true };
  };
}

const CONTACT_CALLER_ROLES: UserRole[] = [
  "talent_community_manager",
  "recruiter",
  "sourcer",
  "tac",
];

export const TILE_DEFINITIONS: Record<TileType, TileDefinition> = {
  my_tasks: {
    type: "my_tasks",
    label: "Moje zadania",
    description: "Dzisiejsze terminy, spotkania i nieprzeczytane powiadomienia.",
    category: "my_work",
    defaultSize: { w: 6, h: 5 },
    minSize: { w: 4, h: 3 },
    ownChrome: true,
    availability: ANY,
  },
  my_next_steps: {
    type: "my_next_steps",
    label: "Następne kroki",
    description: "Karty, które czekają na Twój ruch, pogrupowane po rekrutacjach.",
    category: "my_work",
    defaultSize: { w: 6, h: 5 },
    minSize: { w: 4, h: 3 },
    ownChrome: true,
    availability: needsSection("pipeline", "Rekrutacje"),
  },
  my_contact_queue: {
    type: "my_contact_queue",
    label: "Moja kolejka kontaktów",
    description: "Kandydaci do zadzwonienia dziś.",
    category: "my_work",
    defaultSize: { w: 6, h: 4 },
    minSize: { w: 4, h: 3 },
    ownChrome: true,
    availability: needsRole(
      CONTACT_CALLER_ROLES,
      "Dla rekruterów, sourcerów, TAC i TCM",
    ),
  },
  my_priority_queue: {
    type: "my_priority_queue",
    label: "Moje priorytety",
    description: "Rekrutacje z priorytetem przydzielonym Tobie.",
    category: "my_work",
    defaultSize: { w: 6, h: 4 },
    minSize: { w: 4, h: 3 },
    ownChrome: true,
    availability: needsRole(
      ["recruiter", "sourcer", "tac"],
      "Dla rekruterów, sourcerów i TAC",
    ),
  },
  my_people: {
    type: "my_people",
    label: "Moi ludzie",
    description: "Ile osób z Twojej listy czeka na projekt i ile nowych dopasowań.",
    category: "my_work",
    defaultSize: { w: 4, h: 2 },
    minSize: { w: 3, h: 2 },
    ownChrome: false,
    availability: (user) =>
      hasCapability(user, "nav.my_people")
        ? { ok: true }
        : { ok: false, reason: "Wymaga dostępu do bazy kandydatów" },
  },
  my_kpis_today: {
    type: "my_kpis_today",
    label: "Moje KPI dziś",
    description: "Postęp dziennych i tygodniowych celów.",
    category: "my_work",
    defaultSize: { w: 6, h: 3 },
    minSize: { w: 4, h: 2 },
    ownChrome: false,
    availability: needsSection("insights", "Insights"),
  },
  my_onboarding: {
    type: "my_onboarding",
    label: "Onboarding",
    description: "Lista kroków wdrożenia do pracy w NEXUS.",
    category: "my_work",
    defaultSize: { w: 6, h: 3 },
    minSize: { w: 4, h: 2 },
    ownChrome: true,
    availability: ANY,
  },
  my_recruitments: {
    type: "my_recruitments",
    label: "Moje rekrutacje",
    description: "Otwarte rekrutacje, w których jesteś w zespole.",
    category: "recruitment",
    defaultSize: { w: 6, h: 5 },
    minSize: { w: 4, h: 3 },
    ownChrome: true,
    availability: needsSection("pipeline", "Rekrutacje"),
  },
  recruitment_activity: {
    type: "recruitment_activity",
    label: "Aktywność rekrutacyjna",
    description: "Dzienne i miesięczne liczby: weryfikacje, CV, rozmowy.",
    category: "recruitment",
    defaultSize: { w: 12, h: 5 },
    minSize: { w: 6, h: 3 },
    ownChrome: true,
    availability: needsSection("pipeline", "Rekrutacje"),
  },
  recruitment_competence: {
    type: "recruitment_competence",
    label: "Procesy wg kompetencji",
    description: "Wszystkie procesy z filtrem kategorii, etapami i faworytami.",
    category: "recruitment",
    defaultSize: { w: 12, h: 6 },
    minSize: { w: 6, h: 4 },
    ownChrome: true,
    availability: needsSection("pipeline", "Rekrutacje"),
  },
  team_workload: {
    type: "team_workload",
    label: "Obciążenie zespołu",
    description: "Ile rekrutacji ma każda osoba z zespołu i kto ma miejsce.",
    category: "team",
    defaultSize: { w: 12, h: 5 },
    minSize: { w: 6, h: 3 },
    ownChrome: true,
    availability: both(
      needsSection("pipeline", "Rekrutacje"),
      needsRole(["head_of_recruitment"], "Dla Head of Recruitment"),
    ),
  },
  team_allocation: {
    type: "team_allocation",
    label: "Alokacja zespołu",
    description: "Przydział priorytetów, wyjątki i blokery zespołu.",
    category: "team",
    defaultSize: { w: 12, h: 6 },
    minSize: { w: 6, h: 4 },
    ownChrome: true,
    availability: needsRole(
      ["admin", "head_of_recruitment"],
      "Dla administratora i Head of Recruitment",
    ),
  },
  contact_oversight: {
    type: "contact_oversight",
    label: "Nadzór kontaktów",
    description: "Kolejki telefonów zespołu i przekroczone terminy SLA.",
    category: "team",
    defaultSize: { w: 12, h: 5 },
    minSize: { w: 6, h: 3 },
    ownChrome: true,
    availability: needsRole(
      ["admin", "head_of_recruitment"],
      "Dla administratora i Head of Recruitment",
    ),
  },
  my_clients_alerts: {
    type: "my_clients_alerts",
    label: "Moi klienci — sprawy",
    description: "Kończące się zamówienia, niski budżet MD, szkice do uzupełnienia.",
    category: "clients",
    defaultSize: { w: 6, h: 5 },
    minSize: { w: 4, h: 3 },
    ownChrome: true,
    availability: needsSection("delivery", "Delivery"),
  },
  dl_alerts: {
    type: "dl_alerts",
    label: "Alerty Delivery Leada",
    description: "Historia alertów zamówień z eksportem do CSV.",
    category: "clients",
    defaultSize: { w: 12, h: 5 },
    minSize: { w: 6, h: 3 },
    ownChrome: true,
    availability: both(
      needsSection("delivery", "Delivery"),
      needsRole(["delivery_lead"], "Dla Delivery Leadów"),
    ),
  },
  calendar_today: {
    type: "calendar_today",
    label: "Dzisiaj w kalendarzu",
    description: "Twoje spotkania i rozmowy na dziś.",
    category: "calendar",
    defaultSize: { w: 4, h: 3 },
    minSize: { w: 3, h: 2 },
    ownChrome: false,
    availability: ANY,
  },
  metric_number: {
    type: "metric_number",
    label: "Liczba",
    description: "Jedna liczba z porównaniem do poprzedniego okresu.",
    category: "universal",
    defaultSize: { w: 3, h: 2 },
    minSize: { w: 2, h: 2 },
    ownChrome: false,
    availability: ANY,
  },
  metric_chart: {
    type: "metric_chart",
    label: "Wykres",
    description: "Słupki, linia albo tabela — w czasie albo w podziale.",
    category: "universal",
    defaultSize: { w: 6, h: 3 },
    minSize: { w: 3, h: 2 },
    ownChrome: false,
    availability: ANY,
  },
  metric_funnel: {
    type: "metric_funnel",
    label: "Lejek rekrutacji",
    description: "Ile osób doszło do każdego etapu — dla klienta albo całości.",
    category: "recruitment",
    defaultSize: { w: 6, h: 3 },
    minSize: { w: 4, h: 2 },
    ownChrome: false,
    availability: needsSection("pipeline", "Rekrutacje"),
  },
  note: {
    type: "note",
    label: "Notatka i linki",
    description: "Własny tekst i skróty do stron, z których często korzystasz.",
    category: "universal",
    defaultSize: { w: 4, h: 2 },
    minSize: { w: 2, h: 1 },
    ownChrome: false,
    availability: ANY,
  },
};

// ── Szablony: gotowe kafelki z katalogu ──────────────────────────────────────
//
// Szablon = typ + ustawienia startowe. Część „gotowych kafelków" z makiet to
// po prostu kafelek metryki z przygotowaną definicją (np. „Kończące się
// zamówienia"). Każdy da się potem zmienić w ustawieniach.

export interface TileTemplate {
  key: string;
  type: TileType;
  label: string;
  description: string;
  category: TileCategory;
  config: TileConfig;
  size?: Size;
  /** Sekcja wymagana przez źródło metryki (lustro serwerowego katalogu). */
  metricSection?: "pipeline" | "sourcing" | "delivery" | "finance";
}

const cvSentThisWeek: MetricDefinition = {
  source: "pipeline_moves",
  measure: "first_reach",
  stage: "cv_sent",
  filters: { author: "me" },
  group_by: "none",
  period: "last_7_days",
  compare_previous: true,
};

export const TILE_TEMPLATES: TileTemplate[] = [
  ...(Object.values(TILE_DEFINITIONS)
    .filter((d) => !d.type.startsWith("metric_") && d.type !== "note")
    .map((d) => ({
      key: d.type,
      type: d.type,
      label: d.label,
      description: d.description,
      category: d.category,
      config: {},
    })) satisfies TileTemplate[]),
  {
    key: "cv_sent_week",
    type: "metric_number",
    label: "Wysłane CV",
    description: "Ile CV poszło do klientów w ostatnich 7 dniach.",
    category: "my_work",
    config: { title: "Wysłane CV", metric: cvSentThisWeek },
    metricSection: "pipeline",
  },
  {
    key: "hired_month",
    type: "metric_number",
    label: "Zatrudnieni",
    description: "Pierwsze zatrudnienia w tym miesiącu.",
    category: "recruitment",
    config: {
      title: "Zatrudnieni",
      metric: {
        source: "pipeline_moves",
        measure: "first_reach",
        stage: "hired",
        filters: { author: "me" },
        group_by: "none",
        period: "this_month",
        compare_previous: true,
      },
    },
    metricSection: "pipeline",
  },
  {
    key: "funnel",
    type: "metric_funnel",
    label: "Lejek rekrutacji",
    description: "Ile osób doszło do każdego etapu w ostatnich 30 dniach.",
    category: "recruitment",
    config: {
      title: "Lejek rekrutacji",
      metric: {
        source: "pipeline_moves",
        measure: "first_reach",
        stage: null,
        filters: { author: "me" },
        group_by: "stage",
        period: "last_30_days",
      },
    },
    metricSection: "pipeline",
  },
  {
    key: "cv_sent_weekly_chart",
    type: "metric_chart",
    label: "Wysłane CV / tydzień",
    description: "Wysłane CV tydzień po tygodniu — ostatnie 8 tygodni.",
    category: "recruitment",
    config: {
      title: "Wysłane CV / tydzień",
      chart: "bars",
      metric: { ...cvSentThisWeek, group_by: "week", period: "last_8_weeks" },
    },
    size: { w: 8, h: 3 },
    metricSection: "pipeline",
  },
  {
    key: "orders_ending",
    type: "metric_chart",
    label: "Kończące się zamówienia",
    description: "Zamówienia kończące się w ciągu 30 dni, po klientach.",
    category: "clients",
    config: {
      title: "Kończące się zamówienia",
      chart: "table",
      link_to: "/my-clients",
      metric: {
        source: "orders",
        measure: "ending_30_days",
        filters: { author: "all" },
        group_by: "client",
        period: "last_30_days",
      },
    },
    metricSection: "delivery",
  },
  {
    key: "active_contracts",
    type: "metric_number",
    label: "Aktywne kontrakty",
    description: "Ile kontraktów obowiązuje dziś.",
    category: "clients",
    config: {
      title: "Aktywne kontrakty",
      metric: {
        source: "contracts",
        measure: "active_now",
        filters: { author: "all" },
        group_by: "none",
        period: "last_30_days",
      },
    },
    metricSection: "delivery",
  },
  {
    key: "margin_monthly",
    type: "metric_chart",
    label: "Marża miesięczna",
    description: "Marża z kontraktów miesiąc po miesiącu (PLN).",
    category: "finance",
    config: {
      title: "Marża miesięczna",
      chart: "line",
      metric: {
        source: "finance",
        measure: "margin",
        filters: { author: "all" },
        group_by: "month",
        period: "last_12_months",
      },
    },
    size: { w: 8, h: 3 },
    metricSection: "finance",
  },
  {
    key: "margin_by_client",
    type: "metric_chart",
    label: "Marża per klient",
    description: "Dzisiejsza marża miesięczna w podziale na klientów.",
    category: "finance",
    config: {
      title: "Marża per klient",
      chart: "table",
      metric: {
        source: "finance",
        measure: "margin",
        filters: { author: "all" },
        group_by: "client",
        period: "this_month",
      },
    },
    metricSection: "finance",
  },
  {
    key: "note",
    type: "note",
    label: "Notatka i linki",
    description: TILE_DEFINITIONS.note.description,
    category: "universal",
    config: { title: "Notatka", text: "" },
  },
];

// ── Polecane dla roli (pusty pulpit) ─────────────────────────────────────────

const RECOMMENDED_BY_ROLE: Partial<Record<UserRole, string[]>> = {
  recruiter: ["cv_sent_week", "my_recruitments", "my_next_steps", "calendar_today"],
  sourcer: ["cv_sent_week", "my_recruitments", "my_next_steps", "calendar_today"],
  tac: ["cv_sent_week", "my_recruitments", "my_next_steps", "calendar_today"],
  talent_community_manager: [
    "recruitment_activity",
    "funnel",
    "my_contact_queue",
    "calendar_today",
  ],
  head_of_recruitment: [
    "recruitment_activity",
    "team_workload",
    "funnel",
    "contact_oversight",
  ],
  delivery_lead: [
    "my_clients_alerts",
    "orders_ending",
    "active_contracts",
    "calendar_today",
  ],
  finance: ["margin_monthly", "margin_by_client", "active_contracts", "orders_ending"],
  admin: ["recruitment_competence", "orders_ending", "active_contracts", "margin_monthly"],
};

// Kolejność ról: pierwsza pasująca decyduje (konto wielorolowe dostaje
// podpowiedzi najszerszej persony).
const ROLE_PRIORITY: UserRole[] = [
  "admin",
  "finance",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "tac",
  "recruiter",
  "sourcer",
];

export const ROLE_LABELS_PL: Partial<Record<UserRole, string>> = {
  admin: "Administrator",
  finance: "Finanse",
  head_of_recruitment: "Head of Recruitment",
  delivery_lead: "Delivery Lead",
  talent_community_manager: "Talent Community Manager",
  tac: "TAC",
  recruiter: "Rekruter",
  sourcer: "Sourcer",
};

export function templateAvailability(
  template: TileTemplate,
  user: User | null | undefined,
): TileAvailability {
  const base = TILE_DEFINITIONS[template.type].availability(user);
  if (!base.ok) return base;
  if (template.metricSection === "finance") {
    const roles = getUserRoles(user);
    return roles.some((r) => ["admin", "finance", "delivery_lead"].includes(r))
      ? { ok: true }
      : { ok: false, reason: "Kwoty widzą Finanse, administrator i Delivery Lead" };
  }
  if (template.metricSection) {
    const labels = {
      pipeline: "Rekrutacje",
      sourcing: "Kandydaci",
      delivery: "Delivery",
    } as const;
    return hasSectionAccess(user, template.metricSection)
      ? { ok: true }
      : {
          ok: false,
          reason: `Wymaga dostępu do sekcji ${labels[template.metricSection]}`,
        };
  }
  return { ok: true };
}

export function recommendedTemplates(user: User | null | undefined): {
  roleLabel: string | null;
  templates: TileTemplate[];
} {
  const roles = getUserRoles(user);
  const role = ROLE_PRIORITY.find((r) => roles.includes(r)) ?? null;
  const keys = (role && RECOMMENDED_BY_ROLE[role]) || ["calendar_today", "note"];
  const templates = keys
    .map((key) => TILE_TEMPLATES.find((t) => t.key === key))
    .filter((t): t is TileTemplate => Boolean(t))
    .filter((t) => templateAvailability(t, user).ok);
  return { roleLabel: role ? (ROLE_LABELS_PL[role] ?? null) : null, templates };
}

export function tileTitle(tile: Pick<DashboardTile, "type" | "config">): string {
  return tile.config.title?.trim() || TILE_DEFINITIONS[tile.type].label;
}
