import api from "@/lib/api";

/**
 * Klient `/api/insights/*` — powierzchni Insights liczonej z danych
 * natywnych NEXUSA.
 *
 * Świadomie ODDZIELNY od `dashboard-v2-api.ts` i od wrapperów `/api/reports/*`
 * w `api.ts`: tamte endpointy są współdzielone z innymi stronami, więc ani ich
 * semantyka okresu, ani ich guard nie mogą się zmieniać pod potrzeby Insights.
 */

/** Granulacja okresu — lustro `PeriodKind` z backend/app/analytics/periods.py. */
export type InsightsPeriodKind =
  "day" | "week" | "month" | "quarter" | "year" | "custom";

/**
 * Domyślnie pokazujemy POPRZEDNI ZAMKNIĘTY okres, nie bieżący.
 *
 * Bieżący okres jest prawie pusty przez większość swojego trwania: pierwszego
 * dnia miesiąca „ten miesiąc" to jeden dzień danych, a w poniedziałek „ten
 * tydzień" to jeden dzień. Ekran pełen zer czyta się jako „nic się nie dzieje",
 * a znaczy „okres się dopiero zaczął" — i to jest ta sama klasa pomyłki, co
 * awaria renderowana jako brak danych.
 *
 * DynaReporter robił to tak samo (`kpi.ts:38-42` domyślnie brał poprzedni,
 * zamknięty tydzień). Użytkownik nadal może przejść na bieżący strzałką.
 */
export const DEFAULT_INSIGHTS_OFFSET = -1;

export interface InsightsPeriodParams {
  period: InsightsPeriodKind;
  /** 0 = bieżący okres, -1 = poprzedni zamknięty. */
  offset?: number;
  /** Dowolny dzień WEWNĄTRZ żądanego okresu (YYYY-MM-DD). */
  anchor?: string;
  date_from?: string;
  date_to?: string;
}

/** Okno zwrócone przez backend — półotwarte [start, end) w Europe/Warsaw. */
export interface InsightsPeriod {
  kind: InsightsPeriodKind;
  start: string;
  end: string;
  timezone: string;
}

export interface FunnelStage {
  stage: string;
  label: string;
  count: number;
  /**
   * `false` = import z Traffita NIE zna tego etapu. Zero przy takim etapie
   * znaczy „nie odnotowujemy", a nie „nie zdarza się" — UI musi to rozróżnić,
   * bo inaczej brak ewidencji czyta się jako wynik biznesowy.
   */
  mapped_from_traffit: boolean;
  share_pct: number | null;
}

export interface FunnelConversion {
  key: string;
  label: string;
  numerator: number;
  denominator: number;
  /** `null` = zerowy mianownik, czyli luka. Nigdy nie mylić z 0. */
  pct: number | null;
}

export interface FunnelCoverage {
  stage_moves_total: number;
  stage_moves_manual: number;
  manual_pct: number | null;
  unattributed_moves: number;
  stages_not_mapped_from_traffit: string[];
}

export interface RecruitmentFunnelResponse {
  period: InsightsPeriod;
  stages: FunnelStage[];
  conversions: FunnelConversion[];
  coverage: FunnelCoverage;
}

export interface TimeToHireEntry {
  user_id: number;
  name: string;
  hires: number;
  median_days: number | null;
  p90_days: number | null;
}

export interface TimeToHireResponse {
  period: InsightsPeriod;
  entries: TimeToHireEntry[];
  totals: {
    hires: number;
    attributed_hires: number;
    /**
     * Zatrudnienia, których nie da się przypisać nikomu. MUSZĄ być
     * wyrenderowane obok sumy kolumny — bez tego tabela per osoba nie zgadza
     * się z lejkiem i wygląda na zepsutą zamiast na niekompletną.
     */
    unattributed_hires: number;
  };
  min_hires: number;
}

export interface TeamActivityEntry {
  rank: number;
  user_id: number;
  name: string;
  candidates_added: number;
  screenings: number;
  interviews: number;
  placements: number;
  calls: number;
  total_actions: number;
  /** `null` = pusty ranking, czyli brak skali paska. Nigdy nie mylić z 0. */
  share_pct: number | null;
}

export interface TeamActivityResponse {
  period: InsightsPeriod;
  limit: number;
  entries: TeamActivityEntry[];
  totals: { users: number; actions: number };
  /**
   * `user_activities` zapisuje WYŁĄCZNIE czynności wykonane w NEXUSIE — import
   * z Traffita nie tworzy tam ani jednego wiersza. Bez wyrenderowania `note`
   * pusty ranking czyta się jako „zespół nic nie robił”.
   */
  coverage: { source: string; note: string };
}

export interface InviteLinkChannel {
  channel: string;
  /**
   * `true` = kubełek linków bez etykiety. Sam string nie wystarcza — „Bez
   * etykiety” jest legalną nazwą kanału i po tekście nie da się ich odróżnić.
   */
  unlabelled: boolean;
  links_count: number;
  applications: number;
  /** `null` = zero linków, czyli brak mianownika. Legacy zwraca tu `0`. */
  conversion_pct: number | null;
  last_used_at: string | null;
}

export interface InviteLinksResponse {
  period: InsightsPeriod;
  channels: InviteLinkChannel[];
  totals: {
    links: number;
    applications: number;
    candidates: number;
    conversion_pct: number | null;
  };
  /**
   * Co okno FILTRUJE. Licznik aplikacji jest kumulatywny na linku, więc link
   * założony w oknie wnosi też aplikacje sprzed jego granicy — to musi być
   * napisane przy liczbie, nie przemilczane.
   */
  window_scope: {
    channels: string;
    candidates: string;
    applications_are_lifetime_per_link: boolean;
    note: string;
  };
}

export interface InsightsHiringManagerRow {
  contact_id: number;
  contact_name: string;
  position: string | null;
  client_id: number;
  client_name: string;
  jobs_total: number;
  jobs_open: number;
  contracts_total: number;
  contracts_active: number;
  /** `null` = zero rekrutacji. Świadomie NIE przycinane do 100%. */
  contract_rate_pct: number | null;
}

export interface InsightsHiringManagersResponse {
  period: InsightsPeriod;
  limit: number;
  managers: InsightsHiringManagerRow[];
  totals: {
    managers: number;
    jobs_total: number;
    jobs_open: number;
    contracts_total: number;
    contracts_active: number;
    open_rate_pct: number | null;
  };
  /** Ilu HM odsiał `limit`. Przycięta lista bez tej liczby czyta się jako komplet. */
  truncated: number;
  scope: {
    jobs: string;
    contracts: string;
    /** `true` = „Aktywni” to stan NA DZIŚ, nie z końca okna. */
    contracts_active_is_snapshot_now: boolean;
    note: string;
  };
}

export interface AvailablePeriodsResponse {
  granularity: "week" | "month" | "quarter";
  periods: Array<{ start: string; milestones: number }>;
}

function periodQuery(p: InsightsPeriodParams): Record<string, string | number> {
  const q: Record<string, string | number> = { period: p.period };
  if (p.offset !== undefined) q.offset = p.offset;
  if (p.anchor) q.anchor = p.anchor;
  if (p.date_from) q.date_from = p.date_from;
  if (p.date_to) q.date_to = p.date_to;
  return q;
}

// ─────────────────────────────────────────────────────────────────────────────
// Ścieżka rozwoju (D6) — `/api/insights/recruitment/seniority`.
//
// Poziom jest LICZONY PRZY ODCZYCIE z liczby placementów, nigdy przechowywany
// (uzasadnienie: backend/app/services/insights_seniority.py). Konsekwencja dla
// UI: poziom zmienia się, gdy zmienia się historia atrybucji, a nie gdy ktoś
// coś dziś zrobił — dlatego wiersz niesie `first_placement_month`, żeby dało
// się pokazać, na czym poziom stoi.
// ─────────────────────────────────────────────────────────────────────────────

export type SeniorityLevel = "junior" | "senior" | "expert";

export interface SeniorityThresholds {
  senior_placements: number;
  senior_window_months: number;
  expert_placements: number;
  expert_window_months: number;
  /**
   * Alternatywna, wolniejsza ścieżka — na każdym poziomie obowiązuje reguła
   * podstawowa LUB ta. Pominięcie jej w opisie kazałoby ludziom mierzyć się
   * do progu, którego wcale nie muszą osiągnąć.
   */
  senior_alt_placements: number;
  senior_alt_window_months: number;
  expert_alt_placements: number;
  expert_alt_window_months: number;
}

export interface SeniorityWindow {
  months: number;
  /** 'YYYY-MM'. `null` = okno wyłączone (zerowa długość w konfiguracji). */
  start_month: string | null;
  end_month: string;
}

export interface SeniorityEntry {
  user_id: number;
  name: string;
  role: string;
  level: SeniorityLevel;
  total_placements: number;
  /**
   * 'YYYY-MM' pierwszego PRZYPISANEGO placementu albo `null`. `null` znaczy
   * „nie mamy w NEXUSIE ani jednego placementu tej osoby" — to NIE to samo co
   * „ta osoba nic nie dowiozła", więc taki wiersz nie może dostać paska „0/6".
   */
  first_placement_month: string | null;
  placements_in_senior_window: number;
  placements_in_expert_window: number;
  /** `null` = expert (nie ma następnego poziomu) albo próg wyłączony. */
  placements_to_next_level: number | null;
  /** `null` = brak progu. Nigdy nie mylić z 0. Nie jest przycięty do 100. */
  progress_pct: number | null;
  /**
   * 'YYYY-MM' pierwszego miesiąca, w którym reguła danego poziomu została
   * spełniona. `senior_since` jest KOTWICĄ zegara eksperta: do wyższego
   * poziomu liczą się wyłącznie placementy od tego miesiąca w górę. Bez tej
   * daty w wierszu `placements_in_expert_window` wygląda na zaniżony.
   */
  senior_since: string | null;
  expert_since: string | null;
}

export interface SeniorityResponse {
  /** Dzień, na który policzono poziom (YYYY-MM-DD). */
  as_of: string;
  thresholds: SeniorityThresholds;
  window: { senior: SeniorityWindow; expert: SeniorityWindow };
  entries: SeniorityEntry[];
  totals: {
    users: number;
    levels: Record<SeniorityLevel, number>;
  };
  coverage: {
    /** Placementy bez przypisanego operatora (import bez dopasowania). */
    unattributed_placements: number;
    /**
     * Placementy przypisane do kont SPOZA puli — inne role oraz konta-widma
     * (`is_active=false`) zakładane przez import Traffita. Muszą być widoczne,
     * bo inaczej suma tabeli nie zgadza się z lejkiem.
     */
    outside_pool_placements: number;
    note: string;
  };
  /**
   * Osoby, którym poziom SPADŁ między obserwacjami dziennika.
   *
   * Poziom nie degraduje się upływem czasu (okno służy do awansu, nie do
   * cofania), więc spadek zawsze oznacza, że zmieniła się HISTORIA ATRYBUCJI —
   * import przepisał zaległe zatrudnienia, ktoś przepiął placement. Ta lista
   * jest jedynym miejscem, w którym taka zmiana jest widoczna: przy odczycie
   * widać wyłącznie stan bieżący, a poprzedni nie istnieje nigdzie indziej.
   *
   * Pusta tablica to normalny, spodziewany stan. `null` znaczy co INNEGO:
   * dziennika nie dało się odczytać, więc nie wiemy, czy komuś spadł poziom.
   * Renderowanie `null` jako ciszy zamieniłoby awarię w odpowiedź „nikomu nic
   * nie spadło" — trzy stany muszą być rozróżnialne na ekranie.
   */
  regressions: SeniorityRegression[] | null;
}

export interface SeniorityRegression {
  user_id: number;
  name: string;
  level: SeniorityLevel;
  /** Poziom sprzed spadku. Nigdy `null` w tej liście — spadek ma poprzednika. */
  previous_level: SeniorityLevel | null;
  total_placements: number;
  previous_total_placements: number | null;
  /** ISO 8601 — kiedy dziennik ZAUWAŻYŁ spadek, nie kiedy on nastąpił. */
  observed_at: string | null;
  /**
   * Odcisk progów z chwili obserwacji. Różny od bieżącego = poziom spadł, bo
   * operator PODNIÓSŁ poprzeczkę, a nie dlatego, że cofnięto atrybucję.
   */
  thresholds_fingerprint: string;
}

export const insightsApi = {
  recruitmentFunnel: (p: InsightsPeriodParams) =>
    api
      .get<RecruitmentFunnelResponse>("/api/insights/recruitment/funnel", {
        params: periodQuery(p),
      })
      .then((r) => r.data),

  timeToHire: (p: InsightsPeriodParams & { min_hires?: number }) =>
    api
      .get<TimeToHireResponse>("/api/insights/recruitment/time-to-hire", {
        params: {
          ...periodQuery(p),
          ...(p.min_hires ? { min_hires: p.min_hires } : {}),
        },
      })
      .then((r) => r.data),

  availablePeriods: (granularity: "week" | "month" | "quarter" = "month") =>
    api
      .get<AvailablePeriodsResponse>(
        "/api/insights/recruitment/available-periods",
        {
          params: { granularity },
        },
      )
      .then((r) => r.data),

  /**
   * Imienny ranking aktywności. Zastępuje `/api/activities/leaderboard`, który
   * stoi na capability `VIEW_RECRUITMENT_RANKING` — dla roli `user` zwracał
   * 403, a sekcja renderowała go jako „brak danych o zespole”. Guard tamtego
   * endpointu ZOSTAJE nietknięty (steruje też dashboardem rekrutera).
   */
  teamActivity: (p: InsightsPeriodParams & { limit?: number }) =>
    api
      .get<TeamActivityResponse>("/api/insights/recruitment/team-activity", {
        params: {
          ...periodQuery(p),
          ...(p.limit ? { limit: p.limit } : {}),
        },
      })
      .then((r) => r.data),

  /**
   * Kanały aplikacyjne. Zastępuje `/api/reports/invite-links` (cztery role,
   * okno KROCZĄCE bez sufitu, `conversion_pct` = 0 przy zerowym mianowniku).
   */
  inviteLinks: (p: InsightsPeriodParams) =>
    api
      .get<InviteLinksResponse>("/api/insights/recruitment/invite-links", {
        params: periodQuery(p),
      })
      .then((r) => r.data),

  /**
   * Ścieżka rozwoju (D6). Bez parametru okresu — poziom liczy się z CAŁEJ
   * historii, a `as_of` służy wyłącznie do odtworzenia stanu na dany dzień.
   */
  seniority: (asOf?: string) =>
    api
      .get<SeniorityResponse>("/api/insights/recruitment/seniority", {
        params: asOf ? { as_of: asOf } : undefined,
      })
      .then((r) => r.data),
};

// ─────────────────────────────────────────────────────────────────────────────
// Zarząd (`/api/insights/board`) i Klienci & Delivery
// (`/api/insights/clients/*`, `/api/insights/delivery-leads*`).
//
// Wszystkie liczby procentowe i kwotowe są `number | null`. `null` ZNACZY
// „nie dało się policzyć" (zerowy mianownik, brak kursu NBP) i musi się
// wyrenderować jako „—”. Zamiana na `0` czyta się jako wynik biznesowy,
// a to jest ta różnica, którą backend świadomie utrzymuje w każdej z tych
// tras (`_ratio` zwraca `None`, nigdy `0.0`).
// ─────────────────────────────────────────────────────────────────────────────

/** Porównanie okresu do poprzedniego. `change_pct === null` = brak mianownika. */
export interface InsightsDelta {
  current: number | null;
  previous: number | null;
  delta: number | null;
  change_pct: number | null;
}

export interface InsightsBoardFinance {
  /** Dzień, NA KTÓRY wyceniono MRR — bez niego nie da się sprawdzić kafla. */
  asof: string;
  basis: string;
  revenue_monthly_pln: number | null;
  consultant_cost_monthly_pln: number | null;
  margin_monthly_pln: number | null;
  margin_pct: number | null;
  active_consultants: number;
  active_contracts: number;
  priced_contracts: number;
  /** Kontrakty bez stawki kandydata — ich marża jest NIEZNANA, nie zerowa. */
  contracts_without_cost_leg: number;
  complete: boolean;
}

export interface InsightsBoardKpis {
  /** Nazwa definicji placementu — do napisania na kaflu (trzy różne w apce). */
  placements_definition: string;
  placements: number;
  verified: number;
  cv_sent: number;
  interview: number;
  funnel_efficiency_pct: number | null;
  jobs_closed: number;
  jobs_closed_with_placement: number;
  hit_ratio_pct: number | null;
  hit_ratio_definition: string;
  finance: InsightsBoardFinance;
}

export interface InsightsBoardTrendMonth {
  month: string;
  label: string;
  asof: string;
  placements: number;
  revenue_monthly_pln: number | null;
  consultant_cost_monthly_pln: number | null;
  margin_monthly_pln: number | null;
  consultants: number;
  active_contracts: number;
  /** `false` = któraś kwota tego miesiąca wypadła z sumy (brak kursu NBP). */
  complete: boolean;
}

export interface InsightsBoardDegraded {
  reasons: string[];
  fx: {
    currencies: string[];
    kpi_contracts_excluded_from_revenue: number;
    kpi_contracts_excluded_from_margin: number;
    months_affected: string[];
  };
  contracts_without_cost_leg: number;
  message: string;
}

export interface InsightsBoardResponse {
  period: InsightsPeriod;
  kpis: InsightsBoardKpis;
  trend: { months: InsightsBoardTrendMonth[] };
  comparison: {
    previous_period: InsightsPeriod;
    previous_asof: string;
    placements: InsightsDelta;
    revenue_monthly_pln: InsightsDelta;
    margin_monthly_pln: InsightsDelta;
    active_consultants: InsightsDelta;
    complete: boolean;
  };
  /** `null` = policzone w całości. Degraduje KAFEL, nie stronę. */
  degraded: InsightsBoardDegraded | null;
}

export interface InsightsClientRankingRow {
  client_id: number;
  name: string;
  industry: string | null;
  head_dl_id: number | null;
  head_dl_name: string | null;
  total_revenue_all_time: number | null;
  active_revenue: number | null;
  monthly_margin_total: number | null;
  active_orders_count: number;
  active_consultants: number;
  active_contracts: number;
  framework_status: string | null;
  framework_expiry_date: string | null;
  /** `false` = brak kursu NBP skasował kwotę z sumy tego wiersza. */
  revenue_complete: boolean;
  margin_complete: boolean;
}

export interface InsightsClientsRankingResponse {
  period: InsightsPeriod;
  valuation: { on: string; basis: string; note: string };
  /**
   * Kafle są FOLDEM po tej samej liście, którą niesie `clients` — kwoty
   * sumują się z już zaokrąglonych składników, więc kafel da się sprawdzić
   * dodając kolumnę na ekranie. Nie licz ich drugim zapytaniem.
   */
  totals: {
    clients: number;
    active_clients: number;
    active_consultants: number;
    active_contracts: number;
    active_orders_count: number;
    monthly_margin_complete: boolean;
    revenue_complete: boolean;
    monthly_margin_total: number;
    total_revenue_all_time: number;
    active_revenue: number;
  };
  clients: InsightsClientRankingRow[];
}

export interface InsightsClientHitRatioRow {
  client_id: number;
  client_name: string;
  client_status: string | null;
  closed_jobs: number;
  filled_jobs: number;
  lost_jobs: number;
  total_vacancies: number;
  placements: number;
  hit_ratio: number | null;
  fill_rate: number | null;
  active_jobs: number;
  /** `null` = nie da się ocenić. To NIE jest `false`. */
  target_achieved: boolean | null;
  close_reasons: Record<string, number>;
}

export interface InsightsClientAtRiskRow extends InsightsClientHitRatioRow {
  prev_hit_ratio: number;
  prev_closed_jobs: number;
  delta_pp: number;
}

export interface InsightsClientsHitRatioResponse {
  period: InsightsPeriod;
  placement_definition: string;
  sort: string;
  /** Próg odsiewu ECHOWANY przez serwer — kafle liczą się PO tym filtrze. */
  min_closed: number;
  excluded_reasons: string[];
  clients: InsightsClientHitRatioRow[];
  overall: {
    total_clients: number;
    clients_with_closed_jobs: number;
    total_closed_jobs: number;
    total_filled_jobs: number;
    total_lost_jobs: number;
    total_vacancies: number;
    total_placements: number;
    global_hit_ratio: number | null;
    global_fill_rate: number | null;
    avg_hit_ratio: number | null;
    avg_fill_rate: number | null;
    target_count: number;
    hit_ratio_target_pct: number;
  };
  at_risk: {
    previous_period: InsightsPeriod;
    drop_threshold_pp: number;
    min_closed: number;
    clients: InsightsClientAtRiskRow[];
    /**
     * Klienci bez punktu odniesienia w poprzednim oknie. Bez tej liczby pusta
     * lista at-risk czyta się jako „nikt nie spada", a znaczy „nie było czego
     * porównać".
     */
    not_comparable: number;
  };
}

export interface InsightsDeliveryLeadRow {
  user_id: number;
  name: string;
  is_active: boolean;
  total_requests: number;
  total_vacancies: number;
  placements: number;
  hit_ratio: number | null;
  fill_rate: number | null;
  avg_vacancies_per_request: number | null;
  open_requests: number;
  open_vacancies: number;
  target_achieved: boolean | null;
  clients: string[];
}

export interface InsightsDeliveryLeadsResponse {
  period: InsightsPeriod;
  /** Ranking dotyczy WYŁĄCZNIE ofert tego typu — nie zsumuje się do lejka. */
  recruitment_type: string;
  hit_ratio_target_pct: number;
  /** `snapshot_now` = otwarty pipeline NIE jest liczony w oknie. */
  open_pipeline_scope: string;
  /** Licznik i mianownik hit ratio pochodzą z różnych kohort. */
  hit_ratio_is_cross_cohort: boolean;
  per_dl: InsightsDeliveryLeadRow[];
  overall: {
    dl_count: number;
    total_requests: number;
    total_vacancies: number;
    total_placements: number;
    total_open_requests: number;
    total_open_vacancies: number;
    hit_ratio: number | null;
    fill_rate: number | null;
    avg_hit_ratio: number | null;
    dl_with_hit_ratio: number;
    not_assessable_count: number;
    target_count: number;
  };
  /** Org-level, NIGDY w czyimś wierszu. Musi być widoczne obok rankingu. */
  unattributed: {
    requests: number;
    vacancies: number;
    placements: number;
    open_requests: number;
  };
}

export interface InsightsPlacementsByClientResponse {
  period: InsightsPeriod;
  recruitment_type: string;
  total_placements: number;
  clients: Array<{
    client_id: number | null;
    client_name: string;
    placements: number;
    share_pct: number | null;
  }>;
}

export interface InsightsDeliveryLeadTrendResponse {
  dl_id: number;
  name: string;
  is_active: boolean;
  months: number;
  recruitment_type: string;
  /** `false` — każdy punkt to OSOBNE okno [start, end), nie ogon do dziś. */
  cumulative: boolean;
  trend: Array<{
    month: string;
    period: InsightsPeriod;
    requests: number;
    vacancies: number;
    placements: number;
    hit_ratio: number | null;
    fill_rate: number | null;
  }>;
}

export interface InsightsHitRatioOptions {
  min_closed?: number;
  sort?: "hit_ratio" | "volume" | "name";
  exclude_reasons?: string;
  drop_pp?: number;
  at_risk_min_closed?: number;
}

/**
 * Klucze react-query współdzielone przez sekcję i panel.
 *
 * Panel powtarza zapytanie sekcji WYŁĄCZNIE po to, żeby `PeriodPicker` mógł
 * pokazać okno policzone przez serwer. Deduplikacja działa tylko przy
 * IDENTYCZNYM kluczu, więc klucz ma jedno źródło — dwie literalne tablice
 * rozjechałyby się po pierwszym refaktorze i panel odpalałby drugie zapytanie.
 */
export const insightsQueryKeys = {
  board: (p: InsightsPeriodParams) => ["insights", "board", p] as const,
  clientsRanking: (p: InsightsPeriodParams) =>
    ["insights", "clients", "ranking", p] as const,
  clientsHitRatio: (p: InsightsPeriodParams, o: InsightsHitRatioOptions) =>
    ["insights", "clients", "hit-ratio", p, o] as const,
  deliveryLeads: (p: InsightsPeriodParams) =>
    ["insights", "delivery-leads", p] as const,
  placementsByClient: (p: InsightsPeriodParams) =>
    ["insights", "delivery-leads", "by-client", p] as const,
  deliveryLeadTrend: (dlId: number, months: number) =>
    ["insights", "delivery-leads", "trend", dlId, months] as const,
  teamActivity: (p: InsightsPeriodParams, limit?: number) =>
    ["insights", "recruitment", "team-activity", p, limit ?? null] as const,
  inviteLinks: (p: InsightsPeriodParams) =>
    ["insights", "recruitment", "invite-links", p] as const,
  hiringManagers: (p: InsightsPeriodParams) =>
    ["insights", "clients", "hiring-managers", p] as const,
};

export const insightsBoardApi = {
  board: (p: InsightsPeriodParams) =>
    api
      .get<InsightsBoardResponse>("/api/insights/board", {
        params: periodQuery(p),
      })
      .then((r) => r.data),

  clientsRanking: (p: InsightsPeriodParams) =>
    api
      .get<InsightsClientsRankingResponse>("/api/insights/clients/ranking", {
        params: periodQuery(p),
      })
      .then((r) => r.data),

  clientsHitRatio: (p: InsightsPeriodParams, o: InsightsHitRatioOptions = {}) =>
    api
      .get<InsightsClientsHitRatioResponse>("/api/insights/clients/hit-ratio", {
        params: { ...periodQuery(p), ...o },
      })
      .then((r) => r.data),

  deliveryLeads: (p: InsightsPeriodParams) =>
    api
      .get<InsightsDeliveryLeadsResponse>("/api/insights/delivery-leads", {
        params: periodQuery(p),
      })
      .then((r) => r.data),

  placementsByClient: (p: InsightsPeriodParams) =>
    api
      .get<InsightsPlacementsByClientResponse>(
        "/api/insights/delivery-leads/placements-by-client",
        { params: periodQuery(p) },
      )
      .then((r) => r.data),

  deliveryLeadTrend: (dlId: number, months: number) =>
    api
      .get<InsightsDeliveryLeadTrendResponse>(
        `/api/insights/delivery-leads/${dlId}/trend`,
        { params: { months } },
      )
      .then((r) => r.data),

  /**
   * Ranking hiring managerów. Zastępuje `/api/reports/hiring-managers`, który
   * stoi na trzech rolach (admin / HoR / finance) i nie zna okresu w ogóle.
   * Guard tamtego routera ZOSTAJE nietknięty.
   */
  hiringManagers: (p: InsightsPeriodParams) =>
    api
      .get<InsightsHiringManagersResponse>(
        "/api/insights/clients/hiring-managers",
        { params: periodQuery(p) },
      )
      .then((r) => r.data),
};
