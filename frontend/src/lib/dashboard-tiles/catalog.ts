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

import type { HrConfig } from "@/lib/api/hr";
import type {
  DashboardTile,
  MetricDefinition,
  TileConfig,
  TileType,
} from "@/lib/api/userDashboard";
import { hasCapability } from "@/lib/capabilities";
import { canCustomizeBoardPanel } from "@/lib/dashboard-panels";
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
  | "people"
  | "universal";

export const TILE_CATEGORY_LABELS: Record<TileCategory, string> = {
  my_work: "Moja praca",
  recruitment: "Rekrutacje",
  clients: "Klienci i zamówienia",
  finance: "Finanse",
  team: "Zespół",
  calendar: "Kalendarz",
  people: "Czas i ludzie",
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
  /**
   * Kafelek ma wysokość swojej treści i nie przewija się w sobie — przewija się
   * pulpit. Rozmiar zmienia się tylko w poziomie (decyzja Artura 30.10.2026).
   */
  fitContent?: boolean;
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
  closing_candidates: {
    type: "closing_candidates",
    label: "Kandydaci do zamknięcia",
    description:
      "Osoby w „Akceptacja i umowa”: klient, koszt, przychód, marża, Delivery Lead i rekruter.",
    category: "recruitment",
    defaultSize: { w: 12, h: 6 },
    minSize: { w: 6, h: 3 },
    ownChrome: false,
    availability: needsSection("pipeline", "Rekrutacje"),
  },
  to_complete: {
    type: "to_complete",
    label: "Do uzupełnienia",
    description:
      "Umowy do zamknięcia, rekrutacje do dokończenia i wymagania do poprawy — poza „Czeka na Ciebie”.",
    category: "my_work",
    defaultSize: { w: 12, h: 5 },
    minSize: { w: 4, h: 3 },
    ownChrome: false,
    availability: needsSection("pipeline", "Rekrutacje"),
  },
  pre_contracts: {
    type: "pre_contracts",
    label: "Umowy przedwstępne",
    description:
      "Prośby o umowę przedwstępną do wystawienia i podpisu, umowy wygasające, terminy umowy B2B i decyzje o karze.",
    category: "my_work",
    defaultSize: { w: 4, h: 4 },
    minSize: { w: 3, h: 3 },
    ownChrome: false,
    // Bramka API przedwstępnych, nie sekcja: Viewer ma odczyt Rekrutacji, a API
    // mu odmawia; Rada sekcji nie ma, a przedwstępne prowadzi (22.10.2026).
    availability: (user) =>
      hasCapability(user, "pre_contract.work")
        ? { ok: true }
        : { ok: false, reason: "Wymaga dostępu do umów przedwstępnych" },
  },
  board_tasks: {
    type: "board_tasks",
    label: "Czeka na Ciebie",
    description:
      "Panel „Czeka na Ciebie” jako kafelek — przesuwasz go i usuwasz jak inne. Gdy stoi na pulpicie, nie ma go nad kafelkami.",
    category: "my_work",
    defaultSize: { w: 12, h: 6 },
    // Panel układa listy w trzy kolumny od szerokości ekranu `lg` — węższy
    // kafelek ścisnąłby je do nieczytelności.
    minSize: { w: 6, h: 3 },
    ownChrome: true,
    // Ta sama reguła co usuwanie list panelu (`canCustomizeBoardPanel`).
    availability: (user) =>
      canCustomizeBoardPanel(user)
        ? { ok: true }
        : { ok: false, reason: "Dla Head of Recruitment i admina" },
  },
  recruitment_activity: {
    type: "recruitment_activity",
    label: "Aktywność rekrutacyjna",
    description: "Liczby za wybrany okres: weryfikacje, CV, rozmowy.",
    category: "recruitment",
    defaultSize: { w: 12, h: 5 },
    minSize: { w: 6, h: 3 },
    ownChrome: true,
    // Tabela osób zespołu w okienku 22 rem z przewijaniem w kafelku pokazywała
    // 6 z 23 osób przy 1280 × 720 (Artur, 30.10.2026).
    fitContent: true,
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
  // Prośba Head of Recruitment 23.10.2026: okres na kafelku i lista osób
  // pod liczbą. Lustro `_TEAM_DETAIL_ROLES` trasy listy „Kto się liczy”.
  team_results: {
    type: "team_results",
    label: "Wyniki zespołu",
    description:
      "Weryfikacje, rekomendacje, akceptacje i placementy zespołu w wybranym okresie — kliknij liczbę, żeby zobaczyć osoby.",
    category: "team",
    defaultSize: { w: 8, h: 6 },
    minSize: { w: 5, h: 3 },
    ownChrome: false,
    availability: both(
      needsSection("insights", "Insights"),
      needsRole(
        ["admin", "head_of_recruitment", "delivery_lead", "talent_community_manager", "finance"],
        "Dla liderów zespołu",
      ),
    ),
  },
  // „Ludzie w NEXUSIE” (17.10.2026). Moduł i kartotekę zna dopiero
  // `/api/hr/config` — rozstrzyga je `hrTileGate`; tu tylko to, co widać z konta.
  hr_substitution: {
    type: "hr_substitution",
    label: "W zastępstwie",
    description:
      "Praca kolegi, którego dziś zastępujesz: jego rekrutacje, rozmowy u klienta i kandydaci w procesie.",
    category: "people",
    defaultSize: { w: 6, h: 4 },
    minSize: { w: 4, h: 3 },
    ownChrome: false,
    availability: ANY,
  },
  hr_my_time: {
    type: "hr_my_time",
    label: "Mój czas",
    description: "Ile urlopu zostało, najbliższy urlop i godziny wpisane w tym miesiącu.",
    category: "people",
    defaultSize: { w: 6, h: 3 },
    minSize: { w: 4, h: 3 },
    ownChrome: false,
    availability: ANY,
  },
  hr_approvals: {
    type: "hr_approvals",
    label: "Do akceptacji",
    description: "Wnioski urlopowe i timesheety, które czekają na Twoją decyzję.",
    category: "people",
    defaultSize: { w: 4, h: 3 },
    minSize: { w: 3, h: 2 },
    ownChrome: false,
    availability: ANY,
  },
  // Opieka nad konsultantami (22.10.2026). Moduł zna `/api/hr/config` —
  // rozstrzyga `hrTileGate`; tu rola i sekcja jak bramki tras opieki.
  care_mine: {
    type: "care_mine",
    label: "Moja opieka",
    description:
      "Rozmowy z konsultantami i opinie menedżerów po terminie i do piątku — z tablicy „Do zrobienia” w Opiece.",
    category: "people",
    defaultSize: { w: 6, h: 4 },
    minSize: { w: 4, h: 3 },
    ownChrome: false,
    // Lustro `require_hr_care_reader`: sekcja Delivery (rola Automatyzacje odpada na serwerze).
    availability: needsSection("delivery", "Delivery"),
  },
  care_at_risk: {
    type: "care_at_risk",
    label: "Zagrożeni konsultanci",
    description:
      "Konsultanci ze zdrowiem relacji „Ryzyko” w Twoim zakresie — z powodem i linkiem do karty.",
    category: "people",
    defaultSize: { w: 6, h: 4 },
    minSize: { w: 4, h: 3 },
    ownChrome: false,
    // Zdrowie widzi krąg D11 (opiekun, DL, HoR, admin); lista — sekcja Delivery.
    availability: both(
      needsSection("delivery", "Delivery"),
      needsRole(
        ["admin", "delivery_lead", "talent_community_manager", "head_of_recruitment"],
        "Dla opiekunów, Delivery Leadów i Head of Recruitment",
      ),
    ),
  },
  equipment_tasks: {
    type: "equipment_tasks",
    label: "Sprzęt do zrobienia",
    description: "Zestawy do przygotowania, zwroty i protokoły czekające na podpis — najbliższe terminy.",
    category: "people",
    defaultSize: { w: 6, h: 4 },
    minSize: { w: 4, h: 3 },
    ownChrome: false,
    // Lustro `_manager` w `backend/app/api/equipment.py` (uprawnienie „Sprzęt”).
    availability: (user) =>
      hasPermission(user, "equipment")
        ? { ok: true }
        : {
            ok: false,
            reason: `Wymaga uprawnienia „${permissionLabel("equipment")}”`,
          },
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

// ── „Ludzie w NEXUSIE”: moduł, kartoteka, przełożony ──────────────────────────

/** Stan modułów i praw osoby z `/api/hr/config`; brak = jeszcze nie wiadomo albo awaria. */
export type TileHrContext = Pick<HrConfig, "open_modules" | "me"> | null | undefined;

export const HR_TILE_TYPES: ReadonlySet<TileType> = new Set<TileType>([
  "hr_substitution",
  "hr_my_time",
  "hr_approvals",
  "equipment_tasks",
  "care_mine",
  "care_at_risk",
]);

const OK: TileAvailability = { ok: true };

/**
 * Kafelki „Ludzi w NEXUSIE”: przy wyłączonym module (albo nieznanym stanie
 * modułów) nie ma ich w katalogu ani w układzie roli — `"hidden"`, bo funkcja
 * nie istnieje, a nie brakuje do niej uprawnień. Gdy moduł działa, część
 * kafelków wymaga kartoteki albo roli przełożonego — wtedy powód, jak przy
 * innych kafelkach. Lustro bramek tras: `require_hr_self_service`,
 * `require_hr_leave_approver` / `require_hr_time_approver`,
 * `require_hr_substitution_reader`, `require_hr_equipment`, a dla opieki
 * (`care_mine`, `care_at_risk`) — moduł `care` (`require_hr_care_reader`).
 */
export function hrTileGate(type: TileType, hr: TileHrContext): TileAvailability | "hidden" {
  if (!HR_TILE_TYPES.has(type)) return OK;
  if (!hr) return "hidden";
  const { open_modules: open, me } = hr;
  switch (type) {
    case "hr_substitution":
      return open.leave ? OK : "hidden";
    case "hr_my_time":
      if (!open.leave && !open.time) return "hidden";
      return me.has_profile
        ? OK
        : { ok: false, reason: "Dla osób z kartoteką w NEXUSIE — założą ją Kadry" };
    case "hr_approvals":
      if (!open.leave && !open.time) return "hidden";
      return me.is_admin || me.people_admin || me.timesheets === true || me.is_manager
        ? OK
        : { ok: false, reason: "Dla koordynatorów i Kadr" };
    case "equipment_tasks":
      return open.equipment ? OK : "hidden";
    case "care_mine":
    case "care_at_risk":
      return open.care ? OK : "hidden";
    default:
      return OK;
  }
}

/** Czy szablon w ogóle istnieje dla tej osoby (wyłączony moduł = nie ma go w katalogu). */
export function isTemplateOffered(template: TileTemplate, hr: TileHrContext): boolean {
  return hrTileGate(template.type, hr) !== "hidden";
}

export function templateAvailability(
  template: TileTemplate,
  user: User | null | undefined,
  hr?: TileHrContext,
): TileAvailability {
  const base = TILE_DEFINITIONS[template.type].availability(user);
  if (!base.ok) return base;
  const gate = hrTileGate(template.type, hr);
  if (gate === "hidden") return { ok: false, reason: "Moduł „Ludzi w NEXUSIE” jest wyłączony" };
  if (!gate.ok) return gate;
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
