import api from "@/lib/api";

/**
 * Klient dwóch powierzchni aktywności zespołu pokazywanych na `/insights`:
 * Power Calling (`/api/reports/power-calling`) i LinkedIn Performance
 * (`/api/linkedin-metrics/summary`).
 *
 * Świadomie ODDZIELNY plik od `insights-api.ts`: tamten obsługuje `/api/insights/*`,
 * czyli endpointy liczone przez `resolve_period` (okno kalendarzowe, offset,
 * `cache_suffix`). Te dwa endpointy są STARSZE i mają WŁASNE, nieprzystające
 * pojęcia okna:
 *
 *   - Power Calling przyjmuje `offset_weeks` (0 = bieżący tydzień ISO) i nie zna
 *     miesiąca ani kwartału;
 *   - LinkedIn `/summary` przyjmuje samą granulację i liczy okno OD DZIŚ —
 *     nie da się poprosić o poprzedni miesiąc.
 *
 * Wciśnięcie ich do `InsightsPeriodParams` udawałoby, że honorują `PeriodPicker`,
 * a one go zignorują — i użytkownik dostałby liczby z innego okna pod etykietą
 * wybranego. Dlatego typy są tu osobne i sekcje niosą własne sterowanie.
 */

// ── Power Calling ──────────────────────────────────────────────────────

/**
 * Skąd pochodzi mianownik dni roboczych. `"unavailable"` = integracja z COMPASSEM
 * nie dowiozła danych, więc NIKT nie jest oceniony (a nie: „nikt nie spełnił").
 */
export type PowerCallingWorkdaysSource = "compass" | "unavailable";

export interface PowerCallingCategory {
  id: number;
  slug: string;
  name_pl: string;
}

export interface PowerCallingEntry {
  user_id: number;
  name: string;
  role: string;
  primary_category: PowerCallingCategory | null;
  /** Liczba bezwzględna — znana ZAWSZE, także dla wierszy nieocenianych. */
  verifications_week: number;
  /** `null` = brak mianownika. NIGDY nie podstawiaj tu zera. */
  per_day: number | null;
  /** Dni robocze minus zatwierdzony urlop (COMPASS). `null` = nie wiemy. */
  workdays: number | null;
  workdays_source: PowerCallingWorkdaysSource;
  workdays_basis?: string | null;
  /**
   * `null` = NIE WIEMY, czy próg jest spełniony. To nie jest to samo co `false`
   * („sprawdziliśmy i nie spełnia") — backend rozdziela te dwa stany celowo.
   */
  meets_target: boolean | null;
  progress_pct: number | null;
  weekly_target: number;
  /** Kod powodu, dla którego wiersza nie da się ocenić. */
  reason: string | null;
}

export interface PowerCallingResponse {
  week_label: string;
  iso_week: number;
  iso_year: number;
  date_from: string;
  date_to: string;
  target_per_day: number;
  weekly_target: number;
  /**
   * Zawsze `null` — mianownik jest INDYWIDUALNY (urlop jest indywidualny).
   * Pole zostaje w typie, bo backend je zwraca, ale nie ma z niego użytku.
   */
  workdays: number | null;
  workdays_source: PowerCallingWorkdaysSource;
  requirement_text: string;
  entries: PowerCallingEntry[];
  below_target: PowerCallingEntry[];
  met_target: PowerCallingEntry[];
  not_assessable: PowerCallingEntry[];
  /** `null`, gdy nikt nie jest oceniony — zero znaczyłoby „nikt nie spełnił". */
  meets_target_count: number | null;
  not_assessable_count: number;
  total_count: number;
}

/** Lustro `ge=0, le=12` z sygnatury endpointu — front nie może wysłać 422. */
export const POWER_CALLING_MIN_OFFSET_WEEKS = 0;
export const POWER_CALLING_MAX_OFFSET_WEEKS = 12;

/**
 * Domyślnie POPRZEDNI zamknięty tydzień (lustro domyślnej wartości backendu).
 * Bieżący tydzień w poniedziałek to jeden dzień danych — ekran pełen zer czyta
 * się jako „zespół nic nie robi", a znaczy „tydzień się dopiero zaczął".
 */
export const DEFAULT_POWER_CALLING_OFFSET_WEEKS = 1;

// ── LinkedIn Performance ───────────────────────────────────────────────

export type LinkedInPeriodKind = "week" | "month" | "quarter" | "year";

export interface LinkedInUserTotals {
  user_id: number;
  name: string;
  role: string | null;
  cv_added: number;
  messages_sent: number;
  responses_received: number;
  /**
   * UWAGA: backend liczy je przez `_safe_pct`, który przy ZEROWYM mianowniku
   * zwraca `0.0`, a nie `null`. Zero znaczy tam „nie mamy z czego policzyć",
   * ale na ekranie czyta się jako werdykt („0% odpowiedzi"). Dlatego UI liczy
   * te ilorazy samodzielnie z liczb bezwzględnych — patrz `ratio()`. Pola
   * zostają w typie, bo przychodzą w odpowiedzi, ale nie renderujemy ich.
   */
  response_rate: number;
  cv_response_rate: number;
  /** Liczba DNI ZARAPORTOWANYCH (nie dni roboczych) — mianownik „na dzień". */
  days_reported: number;
}

export interface LinkedInSummaryTotals {
  cv_added: number;
  messages_sent: number;
  responses_received: number;
  response_rate: number;
  cv_response_rate: number;
  active_users: number;
}

export interface LinkedInSummaryResponse {
  period: string;
  date_from: string;
  date_to: string;
  per_user: LinkedInUserTotals[];
  /** Backend deklaruje `dict`, więc pola mogą nie dojechać — stąd `Partial`. */
  totals: Partial<LinkedInSummaryTotals>;
}

/** Cel z DynaReportera: 5 CV na dzień. Referencja, NIE mianownik procentu. */
export const LINKEDIN_CV_PER_DAY_TARGET = 5;

/**
 * Iloraz albo `null` przy zerowym (lub nieznanym) mianowniku.
 *
 * To jest cała różnica między tym plikiem a backendowym `_safe_pct`: zerowy
 * mianownik nie jest wynikiem zero, tylko brakiem wyniku.
 */
export function ratio(
  numerator: number | null | undefined,
  denominator: number | null | undefined,
): number | null {
  if (numerator === null || numerator === undefined) return null;
  if (denominator === null || denominator === undefined || denominator <= 0) {
    return null;
  }
  return numerator / denominator;
}

/** Procent albo `null`. Świadomie BEZ przycinania do 100. */
export function pctOf(
  numerator: number | null | undefined,
  denominator: number | null | undefined,
): number | null {
  const r = ratio(numerator, denominator);
  return r === null ? null : r * 100;
}

// ── Klient ─────────────────────────────────────────────────────────────

export const insightsActivityApi = {
  powerCalling: (offsetWeeks: number) =>
    api
      .get<PowerCallingResponse>("/api/reports/power-calling", {
        params: { offset_weeks: offsetWeeks },
      })
      .then((r) => r.data),

  linkedinSummary: (period: LinkedInPeriodKind) =>
    api
      .get<LinkedInSummaryResponse>("/api/linkedin-metrics/summary", {
        params: { period },
      })
      .then((r) => r.data),
};

/**
 * Klucze react-query. Prefiks `["insights", ...]` jest ZNACZĄCY: przycisk
 * „Odśwież" w `PeriodPicker` unieważnia po tym prefiksie, więc bez niego te
 * dwie sekcje jako jedyne zostawałyby na starych danych.
 *
 * Klucz zawiera dokładnie te parametry, które zmieniają odpowiedź (okno) —
 * odpowiednik `period.cache_suffix` po stronie backendu.
 */
export const insightsActivityQueryKeys = {
  powerCalling: (offsetWeeks: number) =>
    ["insights", "power-calling", offsetWeeks] as const,
  linkedinSummary: (period: LinkedInPeriodKind) =>
    ["insights", "linkedin", "summary", period] as const,
};
