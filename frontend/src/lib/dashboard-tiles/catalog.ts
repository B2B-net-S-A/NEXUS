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
import { hasPermission, permissionLabel } from "@/lib/permissions";
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

// Lustro `DlAlertsUser` (backend/app/api/dl_alerts.py). Head of Recruitment
// zdjęty tam 22.09.2026 (audyt U7); tu został — kafelek dawał mu 403
// zamiast „Brak dostępu” (Runda 10, R10-N1-8).
const DL_ALERTS_ROLES: UserRole[] = ["admin", "delivery_lead", "finance"];

const CONTACT_CALLER_ROLES: UserRole[] = [
  "talent_community_manager",
  "recruiter",
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
      "Dla rekruterów i TCM",
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
    availability: needsRole(["recruiter"], "Dla rekruterów"),
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
    ownChrome: false,
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
  request_board: {
    type: "request_board",
    label: "Requesty i obłożenie",
    description:
      "Requesty „Szukamy kandydatów” po kategoriach, kto przy nich pracuje i ile kto ma — na daily.",
    category: "team",
    defaultSize: { w: 12, h: 8 },
    minSize: { w: 8, h: 5 },
    ownChrome: true,
    availability: needsSection("pipeline", "Rekrutacje"),
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
    // FE-N05: `/api/dl-alerts/cards` wpuszcza tylko DL_ALERTS_ROLES — sama
    // sekcja Delivery (np. TCM) dawała kafelek kończący się 403.
    availability: both(
      needsSection("delivery", "Delivery"),
      needsRole(DL_ALERTS_ROLES, "Dla Delivery Leadów, adminów i Finansów"),
    ),
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
  today_cycle: {
    type: "today_cycle",
    label: "Dziś",
    description:
      "Rozmowy u klienta, prepy i telefon do kandydata po rozmowie — z tego, co jest na dziś do zrobienia.",
    category: "calendar",
    defaultSize: { w: 4, h: 5 },
    minSize: { w: 3, h: 3 },
    ownChrome: false,
    // Lustro bramki /calendar (`PIPELINE_OPERATIONAL_ROLES` w middleware)
    // i `RecruitmentReadAccess` na `GET /api/interview-cycle`.
    availability: both(
      needsSection("pipeline", "Rekrutacje"),
      needsRole(
        [
          "admin",
          "head_of_recruitment",
          "delivery_lead",
          "recruiter",
          "talent_community_manager",
          "finance",
        ],
        "Dla osób pracujących przy rekrutacjach",
      ),
    ),
  },
  team_signals: {
    type: "team_signals",
    label: "Gdzie stoi",
    description:
      "Rekrutacje bez ruchu, bez nikogo u klienta, po terminie i nieprzejrzane Ogłoszenia — tylko ponad próg.",
    category: "team",
    defaultSize: { w: 6, h: 4 },
    minSize: { w: 4, h: 3 },
    ownChrome: false,
    // Lustro `VIEW_TEAM_KPI` na `GET /api/insights/team/attention`.
    availability: both(
      needsSection("insights", "Insights"),
      needsRole(
        [
          "admin",
          "head_of_recruitment",
          "delivery_lead",
          "talent_community_manager",
          "finance",
        ],
        "Dla liderów zespołu",
      ),
    ),
  },
  system_status: {
    type: "system_status",
    label: "Stan systemu",
    description:
      "Synchronizacja Traffita, poczta zamówień, automaty, migracje i usługi AI — z publicznej sondy zdrowia.",
    category: "team",
    defaultSize: { w: 6, h: 4 },
    minSize: { w: 4, h: 3 },
    ownChrome: false,
    availability: needsRole(["admin"], "Dla administratora"),
  },
  my_week: {
    type: "my_week",
    label: "Twój tydzień",
    description: "Weryfikacje, CV do klienta i placementy względem Twoich celów KPI.",
    category: "my_work",
    defaultSize: { w: 5, h: 2 },
    minSize: { w: 4, h: 2 },
    ownChrome: false,
    availability: needsSection("insights", "Insights"),
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
    description: "Twoje placementy w tym miesiącu — liczone jak w „Moje KPI”.",
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
      link_to: "/clients?mine=1",
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
    key: "orders_ending_count",
    type: "metric_number",
    label: "Zamówienia kończące się w 30 dni",
    description: "Ile zamówień Twoich klientów kończy się w ciągu 30 dni.",
    category: "clients",
    config: {
      title: "Zamówienia kończące się w 30 dni",
      link_to: "/clients?mine=1",
      metric: {
        source: "orders",
        measure: "ending_30_days",
        filters: { author: "all" },
        group_by: "none",
        period: "last_30_days",
      },
    },
    metricSection: "delivery",
  },
  {
    key: "margin_number",
    type: "metric_number",
    label: "Marża miesięczna (liczba)",
    description: "Dzisiejsza marża miesięczna z kontraktów (PLN), w Twoim zakresie klientów.",
    category: "finance",
    config: {
      title: "Marża / mc",
      metric: {
        source: "finance",
        measure: "margin",
        filters: { author: "all" },
        group_by: "none",
        period: "this_month",
      },
    },
    metricSection: "finance",
  },
  {
    key: "hired_month_all",
    type: "metric_number",
    label: "Zatrudnieni w firmie",
    description: "Placementy całej firmy w tym miesiącu, z porównaniem do poprzedniego.",
    category: "recruitment",
    config: {
      title: "Placementy w tym miesiącu",
      metric: {
        source: "pipeline_moves",
        measure: "first_reach",
        stage: "hired",
        filters: { author: "all" },
        group_by: "none",
        period: "this_month",
        compare_previous: true,
      },
    },
    metricSection: "pipeline",
  },
  {
    key: "team_funnel_week",
    type: "metric_funnel",
    label: "Lejek zespołu · tydzień",
    description: "Ile osób zespół przeprowadził przez każdy etap w ostatnich 7 dniach.",
    category: "team",
    config: {
      title: "Lejek zespołu · 7 dni",
      metric: {
        source: "pipeline_moves",
        measure: "first_reach",
        stage: null,
        filters: { author: "team" },
        group_by: "stage",
        period: "last_7_days",
      },
    },
    metricSection: "pipeline",
  },
  {
    key: "request_board_my_category",
    type: "request_board",
    label: "Requesty i obłożenie · moja kategoria",
    description: "Ta sama tablica co na daily, z filtrem ustawionym na Twoją kategorię.",
    category: "team",
    config: { board_scope: "my_category" },
  },
  {
    key: "request_board_my_lead",
    type: "request_board",
    label: "Requesty i obłożenie · moje requesty",
    description: "Ta sama tablica co na daily, z filtrem „Delivery Lead: ja”.",
    category: "team",
    config: { board_scope: "my_lead" },
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

export function templateAvailability(
  template: TileTemplate,
  user: User | null | undefined,
): TileAvailability {
  const base = TILE_DEFINITIONS[template.type].availability(user);
  if (!base.ok) return base;
  if (template.metricSection === "finance") {
    // Kafelki kwot idą za uprawnieniem „Stawki i kwoty: podgląd”, nie za rolą.
    // U KOGO konto widzi kwoty (Delivery Lead: u swoich klientów), liczy serwer
    // przy każdym zapytaniu metryki.
    return hasPermission(user, "amounts_view")
      ? { ok: true }
      : {
          ok: false,
          reason: `Wymaga uprawnienia „${permissionLabel("amounts_view")}”`,
        };
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

export function tileTitle(tile: Pick<DashboardTile, "type" | "config">): string {
  return tile.config.title?.trim() || TILE_DEFINITIONS[tile.type].label;
}
