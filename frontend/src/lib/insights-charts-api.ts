import api from "@/lib/api";
import type { InsightsPeriod, InsightsPeriodParams } from "@/lib/insights-api";

/**
 * Klient `GET /api/insights/charts/*` — „Statystyki Roczne" i „Analiza
 * Placementów" z zakładki Rekrutacja.
 *
 * Osobny plik od `insights-api.ts` świadomie: tamten jest współdzielony przez
 * wszystkie zakładki Insights i rośnie równolegle w kilku gałęziach naraz,
 * więc dokładanie tam kolejnych typów gwarantuje konflikt scalania na pliku,
 * którego nikt nie czyta w całości. Typ okna importujemy stamtąd — okno MUSI
 * być tym samym oknem co reszta zakładki.
 *
 * Reguła, która przechodzi przez cały ten plik: `number | null` to NIE jest
 * `number` z domyślnym zerem. `null` znaczy „nie dało się policzyć" (zerowy
 * mianownik), `0` znaczy „policzone i wyszło zero". Na wykresie ta różnica
 * jest widoczna gołym okiem: luka przerywa linię, zero ciągnie ją do podłogi.
 */

/** Oś, na której leży seria. Serie różnią się rzędem wielkości ~10×. */
export type YearlyAxis = "left" | "right";

export interface YearlySeries {
  /** Klucz pola w wierszu miesiąca (`verified`, `cv_sent`, …). */
  key: string;
  label: string;
  /**
   * Przypisanie osi jest CZĘŚCIĄ DEFINICJI metryki, nie kosmetyką: na jednej
   * osi placementy (dziesiątki) leżą płasko przy zerze obok weryfikacji
   * (setki), więc wykres twierdziłby, że nikogo nie zatrudniamy.
   */
  axis: YearlyAxis;
}

export interface YearlyConversionSeries {
  /** Klucz pola w wierszu miesiąca — zawsze z prefiksem `conv_`. */
  key: string;
  label: string;
}

export interface YearlyMonthRow {
  /** Pierwszy dzień miesiąca, `YYYY-MM-DD`. */
  month: string;
  /** Trzyliterowa etykieta PL z serwera (locale kontenera nie decyduje). */
  label: string;
  /**
   * Miesiąc W TOKU — ma mniej dni niż pozostałe, więc spadek na jego słupku
   * nie jest wynikiem zespołu. Miesiące, które się jeszcze nie zaczęły, nie
   * mają wiersza w ogóle.
   */
  is_partial: boolean;
  verified: number;
  cv_sent: number;
  interview: number;
  hired: number;
  /** `null` = zerowy mianownik w tym miesiącu, czyli LUKA. Nigdy nie 0. */
  conv_verified_to_cv_sent: number | null;
  conv_cv_sent_to_interview: number | null;
  conv_interview_to_hired: number | null;
  conv_verified_to_hired: number | null;
  /**
   * Serie są opisane metadanymi z serwera, więc wykres sięga po pole po
   * kluczu (`series[i].key`), a nie po nazwie zapisanej w kodzie. Bez tego
   * indeksu dostęp dynamiczny nie typuje się, a rozjazd nazw między legendą
   * a danymi jest niewykrywalny wzrokiem.
   */
  [key: string]: number | string | boolean | null;
}

export interface YearlyStatsResponse {
  period: InsightsPeriod;
  year: number;
  months: YearlyMonthRow[];
  series: YearlySeries[];
  conversion_series: YearlyConversionSeries[];
  totals: Record<string, number>;
}

export interface PlacementPersonSlice {
  /** `null` = kamień bez atrybucji (ruch zaimportowany z Traffita). */
  user_id: number | null;
  /** Zawsze niepusty podpis — „(nieprzypisane)" zamiast pustego wycinka. */
  name: string;
  placements: number;
  /** `null` = puste okno (zerowy mianownik). Nigdy nie 0. */
  share_pct: number | null;
  /** `false` = wiersz zbiorczy, NIE osoba. Nie liczy się do kafla „Osoby". */
  attributed: boolean;
}

export interface PlacementClientSlice {
  client_id: number | null;
  name: string;
  placements: number;
  share_pct: number | null;
  attributed: boolean;
}

export interface PlacementAnalysisTotals {
  /** Liczba OSÓB — wiersz „(nieprzypisane)" się tu nie liczy. */
  people: number;
  placements: number;
  clients: number;
  /** Placementy bez autora. Zostają w donucie, żeby sumował się do kafla. */
  unattributed_placements: number;
  /** Placementy pary, której oferta zniknęła z bazy. */
  placements_without_job: number;
}

export interface PlacementAnalysisResponse {
  period: InsightsPeriod;
  totals: PlacementAnalysisTotals;
  by_person: PlacementPersonSlice[];
  by_client: PlacementClientSlice[];
  /** Kod definicji placementu — front nie zgaduje, którą z trzech ogląda. */
  placements_definition: string;
}

/** Lokalna kopia — `periodQuery` z `insights-api.ts` nie jest eksportowane. */
function periodQuery(p: InsightsPeriodParams): Record<string, string | number> {
  const q: Record<string, string | number> = { period: p.period };
  if (p.offset !== undefined) q.offset = p.offset;
  if (p.anchor) q.anchor = p.anchor;
  if (p.date_from) q.date_from = p.date_from;
  if (p.date_to) q.date_to = p.date_to;
  return q;
}

export const insightsChartsApi = {
  /**
   * Rok kalendarzowy, NIE okno z `PeriodPicker`a. Dwanaście punktów sterowane
   * oknem „miesiąc" zwinęłoby się do jednego punktu i przestało być wykresem.
   * Pominięty `year` = rok bieżący (rozstrzyga serwer, w Europe/Warsaw —
   * przeglądarka użytkownika może być w innej strefie i o północy 31 grudnia
   * pokazałaby inny rok niż dane).
   */
  yearlyStats: (year?: number) =>
    api
      .get<YearlyStatsResponse>("/api/insights/charts/yearly-stats", {
        params: year === undefined ? undefined : { year },
      })
      .then((r) => r.data),

  placementAnalysis: (p: InsightsPeriodParams) =>
    api
      .get<PlacementAnalysisResponse>(
        "/api/insights/charts/placement-analysis",
        { params: periodQuery(p) },
      )
      .then((r) => r.data),
};

export const insightsChartsQueryKeys = {
  /**
   * Rok wchodzi w klucz nawet jako `undefined` — inaczej przełączenie roku
   * serwowałoby dane poprzedniego pod nową etykietą, czyli dokładnie ten sam
   * defekt, przed którym broni `cache_suffix` po stronie serwera.
   */
  yearlyStats: (year?: number) =>
    ["insights", "charts", "yearly", year] as const,
  placementAnalysis: (p: InsightsPeriodParams) =>
    ["insights", "charts", "placements", p] as const,
};
