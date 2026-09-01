/**
 * Budowa eksportów CSV dla paska okresu (`PeriodPicker`).
 *
 * Wyniesione z paneli, bo bez tego przycisk „Eksportuj" był martwy: renderuje
 * się wyłącznie pod propem `csv`, a żaden panel go nie przekazywał — jedynym
 * miejscem w repo, które go podawało, był test pickera. Funkcja z eksportu jest
 * testowalna bez montowania panelu, więc następna zmiana kształtu odpowiedzi
 * wywali test, a nie ciszę.
 *
 * Reguła wspólna dla wszystkich eksportów: **`null` zostaje `null`**, nigdy nie
 * zamienia się w `0` ani w `"0%"`. Zerowy mianownik to luka, a arkusz, który
 * zamienia lukę w zero, kłamie dokładnie tam, gdzie ktoś liczy średnie.
 */

import type {
  InsightsBoardResponse,
  InsightsClientsRankingResponse,
  RecruitmentFunnelResponse,
} from "@/lib/insights-api";
import type { InsightsCsvExport } from "@/components/insights/PeriodPicker";

/** Lejek + konwersje w jednym arkuszu — dwa bloki, jedna kolumna „sekcja". */
export function buildFunnelCsvExport(
  funnel: RecruitmentFunnelResponse | undefined,
): InsightsCsvExport | null {
  if (!funnel) return null;
  const rows: InsightsCsvExport["rows"] = [
    ...funnel.stages.map((s) => [
      "Lejek",
      s.label,
      s.count,
      s.share_pct,
      // Etap, którego import nie odnotowuje, ma zero z braku ewidencji, a nie
      // z braku wyniku — arkusz musi to nieść, inaczej ktoś policzy z niego
      // konwersję i dostanie liczbę o niczym.
      s.mapped_from_traffit ? "" : "brak ewidencji w imporcie",
    ]),
    ...funnel.conversions.map((c) => [
      "Konwersja",
      c.label,
      c.numerator,
      c.pct,
      c.denominator === 0 ? "zerowy mianownik" : "",
    ]),
  ];
  return {
    filename: "insights-rekrutacja-lejek",
    headers: ["Sekcja", "Pozycja", "Liczba", "Udział / konwersja %", "Uwaga"],
    rows,
  };
}

/**
 * Ranking klientów — kwoty tak, jak przyszły z serwera, bez zaokrągleń.
 *
 * Kolumna „Kwoty pełne" niesie `revenue_complete && margin_complete`: brak
 * kursu NBP kasuje składnik z sumy wiersza, a arkusz bez tej informacji
 * podaje kwotę zaniżoną jako kompletną.
 */
export function buildClientsCsvExport(
  ranking: InsightsClientsRankingResponse | undefined,
): InsightsCsvExport | null {
  if (!ranking) return null;
  return {
    filename: "insights-klienci-ranking",
    headers: [
      "Klient",
      "Delivery Lead",
      "Aktywni konsultanci",
      "Aktywne kontrakty",
      "Przychód aktywny",
      "Marża miesięczna",
      "Kwoty pełne",
    ],
    rows: ranking.clients.map((c) => [
      c.name,
      c.head_dl_name,
      c.active_consultants,
      c.active_contracts,
      c.active_revenue,
      c.monthly_margin_total,
      c.revenue_complete && c.margin_complete ? "tak" : "nie",
    ]),
  };
}

/**
 * KPI zarządu — jedna para „metryka / wartość" na wiersz.
 *
 * `null` zostaje pustą komórką: marża bez kursu NBP jest NIEZNANA, a zero
 * w arkuszu czyta się jako „policzone i wyszło zero".
 */
export function buildBoardCsvExport(
  board: InsightsBoardResponse | undefined,
): InsightsCsvExport | null {
  if (!board) return null;
  const k = board.kpis;
  return {
    filename: "insights-zarzad-kpi",
    headers: ["Metryka", "Wartość"],
    rows: [
      ["Placementy", k.placements],
      ["Weryfikacje", k.verified],
      ["Rekomendacje", k.cv_sent],
      ["Interviews", k.interview],
      ["Efektywność lejka %", k.funnel_efficiency_pct],
      ["Rekrutacje zamknięte", k.jobs_closed],
      ["…w tym z placementem", k.jobs_closed_with_placement],
      ["Hit ratio %", k.hit_ratio_pct],
      ["Przychód miesięczny PLN", k.finance.revenue_monthly_pln],
      ["Koszt konsultantów PLN", k.finance.consultant_cost_monthly_pln],
      ["Marża miesięczna PLN", k.finance.margin_monthly_pln],
      ["Marża %", k.finance.margin_pct],
      ["Aktywni konsultanci", k.finance.active_consultants],
      ["Aktywne kontrakty", k.finance.active_contracts],
      ["Kontrakty bez stawki kandydata", k.finance.contracts_without_cost_leg],
      ["Kwoty pełne", k.finance.complete ? "tak" : "nie"],
    ],
  };
}
