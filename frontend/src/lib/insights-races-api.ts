import api from "@/lib/api";

/**
 * Klient wyścigów miesięcznych i Hall of Fame na powierzchni `/insights`.
 *
 * Świadomie ODDZIELNY plik od `insights-api.ts`: tamten obsługuje `/api/insights/*`
 * — routery napisane pod Insights, przyjmujące okno `resolve_period`. Wyścigi
 * jadą na WSPÓŁDZIELONYM `/api/competitions/*`, który zna wyłącznie okres
 * MIESIĘCZNY (`YYYY-MM`) i nie ma pojęcia o `PeriodPicker`ze. Wrzucenie ich do
 * `insights-api.ts` sugerowałoby, że przyjmują `InsightsPeriodParams` — a nie
 * przyjmują i nie mogą, bo wynik wyścigu jest potem ZAMRAŻANY per miesiąc.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Kontrakt z `GET /api/competitions/monthly-races`
// (backend/app/services/competitions.py::compose_monthly_races)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Jedna pozycja wyścigu: `RankedUser.to_dict()` + `rank` + `excluded`.
 *
 * Pola opcjonalne, bo OBA wyścigi jadą tym samym typem, a niosą różne `extras`:
 * Wyścig Rekomendacji dokłada `verifications`/`precision_pct`/`qualified`,
 * Wyścig Placementów wyłącznie `role` (próg 2 placementów jest tam w `HAVING`,
 * więc niezakwalifikowani w ogóle nie wracają z bazy — patrz `RACE_COPY`).
 */
export interface MonthlyRaceEntry {
  user_id: number;
  name: string;
  /** Rekomendacje (Wyścig Rekomendacji) albo placementy (Wyścig Placementów). */
  metric_value: number;
  rank: number;
  /** Lider kwartału — w rankingu zostaje, ale nagrody nie bierze. */
  excluded: boolean;
  role?: string | null;
  hit_ratio?: number | null;
  verifications?: number | null;
  recommendations?: number | null;
  /** UWAGA: backend zwraca tu `0.0` przy zerowym mianowniku — patrz `precisionOf`. */
  precision_pct?: number | null;
  required_verifications?: number | null;
  /** Brak pola = zakwalifikowany (lustro `extras.get("qualified", True)`). */
  qualified?: boolean;
  disqualification_reasons?: string[] | null;

  // ── Mianownik dni roboczych (D5, COMPASS) ────────────────────────────────
  //
  // Backend `compose_monthly_races` DZIŚ TYCH PÓL NIE WYSYŁA. Są w kontrakcie
  // celowo, a nie na zapas: `/api/reports/power-calling` już je oddaje w tym
  // dokładnie kształcie (`workdays`, `per_day`, `workdays_source`), więc gdy
  // wyścig dostanie mianownik z `insights_workdays.working_days_for`, plakietka
  // „X/dzień" zapali się bez zmiany w UI. Do tego czasu `perDayVerifications`
  // zwraca `null` i ekran mówi wprost, że nie wie — NIE dzieli przez stałą.
  workdays?: number | null;
  per_day?: number | null;
  workdays_source?: "compass" | "unavailable" | null;
}

export interface MonthlyRacePrize {
  amount_pln: number;
  name: string;
}

export interface MonthlyRace {
  /** Miesiąc wyścigu w formacie `YYYY-MM`. */
  period: string;
  /**
   * Dni do końca BIEŻĄCEGO miesiąca kalendarzowego — backend liczy je z
   * `business_today()`, nie z `period`. Dla miesiąca zamkniętego ta liczba nie
   * opisuje niczego i UI jej nie pokazuje (patrz `isClosedMonth`).
   */
  days_remaining: number | null;
  prize: MonthlyRacePrize;
  requirements: string[];
  ranking: MonthlyRaceEntry[];
  excluded_user_ids: number[];
  qualified_leader: MonthlyRaceEntry | null;
}

export interface MonthlyRacesResponse {
  recommendations: MonthlyRace;
  placements: MonthlyRace;
}

// ─────────────────────────────────────────────────────────────────────────────
// Kontrakt z `GET /api/competitions/history` i `/current?type=hall_of_fame`
// ─────────────────────────────────────────────────────────────────────────────

export interface FrozenWinner {
  rank: number;
  user_id: number;
  user_name: string;
  metric_value: number;
  points: number | null;
  prize_pln: number | null;
  created_at: string;
}

export interface FrozenPeriod {
  period: string;
  top3: FrozenWinner[];
}

export interface CompetitionHistoryResponse {
  type: string;
  periods: FrozenPeriod[];
}

/** Pozycja rankingu all-time (`/current?type=hall_of_fame`). */
export interface HallOfFameEntry {
  user_id: number;
  name: string;
  metric_value: number;
  /**
   * `false` = były pracownik. Ranking WSZECH CZASÓW świadomie go zostawia —
   * odejście z firmy nie cofa tego, co ktoś osiągnął — więc wiersz musi dać
   * się OZNACZYĆ. `null`/brak = ranking, który tego nie rozróżnia.
   */
  is_active?: boolean | null;
}

/**
 * Ile dorobku stoi POZA rankingiem i wg jakiej reguły.
 *
 * Bez tego lista przycięta do TOP 5 czyta się jako komplet, a po przejściu
 * na atrybucję D2 poza rankingiem zostaje realny kawał bazy: placementy
 * domknięte przez konta administracyjne.
 */
export interface HallOfFameScope {
  ranked_placements: number;
  outside_role_placements: number;
  unattributed_placements: number;
  /** Mianownik dla „TOP 5" — bez niego lista nie mówi, z ilu osób wybrano. */
  ranked_people: number;
  roles: string[];
  /** Kod definicji — ten sam kontrakt co `placements_definition` w wykresach. */
  attribution: string;
}

export interface HallOfFameResponse {
  type: string;
  period: string;
  top3: Array<HallOfFameEntry & { rank?: number; prize_pln?: number | null }>;
  full_ranking: HallOfFameEntry[];
  /** `null` dla pozostałych typów konkursów — one są okresowe. */
  scope?: HallOfFameScope | null;
}

/** Typy konkursów rozpoznawane przez `/history` (lustro `CompetitionType`). */
export const COMPETITION_TYPES = [
  "monthly_recommendations",
  "monthly_placements",
  "quarterly_champions_recruiter",
  "quarterly_champions_dl",
] as const;

export type CompetitionTypeKey = (typeof COMPETITION_TYPES)[number];

export const COMPETITION_TYPE_LABEL: Record<CompetitionTypeKey, string> = {
  monthly_recommendations: "Wyścig Rekomendacji",
  monthly_placements: "Wyścig Placementów",
  quarterly_champions_recruiter: "Liga Mistrzów — Rekrutacja",
  quarterly_champions_dl: "Liga Mistrzów — Delivery",
};

// ─────────────────────────────────────────────────────────────────────────────
// Czyste funkcje — cała arytmetyka ekranu siedzi tutaj, żeby dała się
// przetestować bez montowania sekcji.
// ─────────────────────────────────────────────────────────────────────────────

/** Dlaczego plakietka „X/dzień" nie ma wartości. */
export type PerDayReason = "ok" | "no_workday_data" | "zero_workdays";

export interface PerDayResult {
  /** `null` = nie wiemy. NIGDY nie jest wyliczone ze stałej liczby dni. */
  value: number | null;
  reason: PerDayReason;
}

export const PER_DAY_REASON_LABEL: Record<
  Exclude<PerDayReason, "ok">,
  string
> = {
  no_workday_data: "brak danych o dniach roboczych",
  zero_workdays: "0 dni roboczych w tym miesiącu",
};

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Weryfikacje na dzień roboczy — albo uczciwe „nie wiemy".
 *
 * Mianownik jest INDYWIDUALNY (urlop jest indywidualny) i pochodzi z COMPASSA
 * przez `insights_workdays.working_days_for`. Ta funkcja NIE ZNA żadnej liczby
 * dni: nie dzieli przez 5, przez 21, ani przez `required_verifications / 4`.
 * Podstawienie tu jakiejkolwiek stałej przywróciłoby defekt, dla którego
 * moduł dni roboczych powstał — osoba na urlopie dostawała wtedy plakietkę
 * wyliczoną z dni, których nie przepracowała, i lądowała pod nazwiskiem na
 * liście „poniżej progu".
 *
 * Zero dni roboczych też daje `null`: dzielenie przez zero nie jest oceną
 * (lustro `reports.py` — „zero_workdays" to osobny powód niż „no_workday_data",
 * bo pierwszy znaczy „wiemy i wynosi zero", a drugi „nie wiemy w ogóle").
 */
export function perDayVerifications(entry: MonthlyRaceEntry): PerDayResult {
  const precomputed = finite(entry.per_day);
  if (precomputed !== null) return { value: precomputed, reason: "ok" };

  const workdays = finite(entry.workdays);
  if (workdays === null) return { value: null, reason: "no_workday_data" };
  if (workdays <= 0) return { value: null, reason: "zero_workdays" };

  const verifications = finite(entry.verifications);
  if (verifications === null) return { value: null, reason: "no_workday_data" };
  return { value: verifications / workdays, reason: "ok" };
}

/**
 * Precision rate albo `null`.
 *
 * Backend liczy `round(100.0 * rec / verified, 1) if verified else 0.0` — przy
 * zerowym mianowniku podstawia ZERO, wbrew regule „zerowy mianownik → None".
 * Osoba z rekomendacjami i zerem weryfikacji w oknie dostawałaby więc „0%",
 * czyli werdykt „nic nie trafiło", zamiast „nie ma z czego liczyć". Front
 * przywraca tu myślnik; poprawka po stronie backendu jest poza zakresem tej
 * zmiany (`compose_monthly_races` jest współdzielone z dashboardem).
 */
export function precisionOf(entry: MonthlyRaceEntry): number | null {
  const verifications = finite(entry.verifications);
  if (verifications !== null && verifications <= 0) return null;
  return finite(entry.precision_pct);
}

/** `2026-08` → `Sierpień 2026`. Nierozpoznany napis wraca bez zmian. */
export function formatMonthPl(period: string | null | undefined): string {
  if (!period) return "—";
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return period;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (month < 1 || month > 12) return period;
  // `timeZone: "UTC"` jest obowiązkowe: `Date.UTC(2026, 7, 1)` sformatowany
  // w strefie ujemnej cofnąłby się na 31 lipca i miesiąc wyścigu zmieniłby
  // nazwę zależnie od tego, gdzie siedzi przeglądarka.
  const label = new Intl.DateTimeFormat("pl-PL", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, 1)));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

/**
 * Bieżący miesiąc (`YYYY-MM`) w kalendarzu WARSZAWSKIM.
 *
 * Strefa jest przybita, a nie brana z przeglądarki: granice okresów w
 * `competitions.py` liczy `local_month_bounds` w Europe/Warsaw, więc laptop
 * ustawiony na UTC uznawałby pierwsze dwie godziny polskiego miesiąca za
 * miesiąc poprzedni i pokazywał trwający wyścig jako „Zakończony".
 */
export function currentMonthKey(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
  }).formatToParts(now);
  const year = parts.find((p) => p.type === "year")?.value ?? "";
  const month = parts.find((p) => p.type === "month")?.value ?? "";
  return `${year}-${month}`;
}

/** Czy miesiąc wyścigu już się domknął (wtedy odliczanie nie ma sensu). */
export function isClosedMonth(period: string, now: Date = new Date()): boolean {
  if (!/^\d{4}-\d{2}$/.test(period)) return false;
  return period < currentMonthKey(now);
}

/**
 * Miesiąc (`YYYY-MM`) z okna rozwiązanego PRZEZ SERWER.
 *
 * `null` dla każdej innej granulacji niż miesiąc — kwartał ma trzy miesiące
 * i pokazanie wyścigu za pierwszy z nich pod nagłówkiem „Q3" byłoby cichym
 * podmienieniem okresu. Wtedy sekcja pyta o bieżący miesiąc i podpisuje go
 * własnym nagłówkiem, zamiast udawać, że słucha `PeriodPicker`a.
 */
export function monthFromResolvedPeriod(
  resolved: { kind: string; start: string } | null | undefined,
): string | null {
  if (!resolved || resolved.kind !== "month") return null;
  const match = /^(\d{4})-(\d{2})/.exec(resolved.start);
  return match ? `${match[1]}-${match[2]}` : null;
}

// ─────────────────────────────────────────────────────────────────────────────

export const racesApi = {
  /** Oba wyścigi naraz. Bez `month` backend bierze bieżący miesiąc. */
  monthlyRaces: (month?: string | null) =>
    api
      .get<MonthlyRacesResponse>("/api/competitions/monthly-races", {
        params: month ? { period: month } : undefined,
      })
      .then((r) => r.data),

  /** Ranking all-time po placementach (`hall_of_fame` w `compute_live`). */
  hallOfFameAllTime: () =>
    api
      .get<HallOfFameResponse>("/api/competitions/current", {
        params: { type: "hall_of_fame" },
      })
      .then((r) => r.data),

  /** Zamrożone podia z `competition_winners`. */
  history: (type: CompetitionTypeKey, limit = 6) =>
    api
      .get<CompetitionHistoryResponse>("/api/competitions/history", {
        params: { type, limit },
      })
      .then((r) => r.data),
};
