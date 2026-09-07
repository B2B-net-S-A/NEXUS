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
  InsightsDeliveryLeadsResponse,
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
 * Ranking Delivery Leadów — jeden wiersz na osobę plus wiersz org-level.
 *
 * Wiersz „Bez przypisanego DL" MUSI trafić do arkusza: bez niego kolumny nie
 * sumują się do wartości, którą pokazuje kokpit, i ktoś liczący średnią
 * z eksportu dostanie inną liczbę niż z ekranu. To ta sama reguła co przy
 * wierszu „Nieprzypisane" w tabeli zespołu — brak atrybucji jest faktem
 * o danych, nie wierszem do pominięcia.
 */
export function buildDeliveryLeadsCsvExport(
  dls: InsightsDeliveryLeadsResponse | undefined,
): InsightsCsvExport | null {
  if (!dls) return null;
  const u = dls.unattributed;
  return {
    filename: "insights-delivery-lead-ranking",
    headers: [
      "Delivery Lead",
      "Aktywny",
      "Zapytania",
      "Wakaty",
      "Placementy",
      "Hit ratio %",
      "Fill rate %",
      "Otwarte zapytania",
    ],
    rows: [
      ...dls.per_dl.map((d) => [
        d.name,
        d.is_active ? "tak" : "nie",
        d.total_requests,
        d.total_vacancies,
        d.placements,
        d.hit_ratio,
        d.fill_rate,
        d.open_requests,
      ]),
      [
        "Bez przypisanego DL",
        "",
        u.requests,
        u.vacancies,
        u.placements,
        null,
        null,
        u.open_requests,
      ],
    ],
  };
}

/**
 * Rada Nadzorcza — KPI firmy i ranking klientów w JEDNYM arkuszu.
 *
 * Dwa bloki pod wspólnym nagłówkiem, rozróżniane kolumną „Sekcja" — ten sam
 * kompromis co w eksporcie lejka wyżej. Powód jest mechaniczny: `PeriodPicker`
 * przyjmuje JEDEN eksport, a zakładka pokazuje dwie tabele. Osobny builder na
 * ranking klientów, którego nikt by nie podał, byłby martwym kodem ze 100%
 * pokryciem — dokładnie ta klasa błędu, którą złapał PR #1316.
 *
 * `null` zostaje pustą komórką: marża bez kursu NBP jest NIEZNANA, a zero
 * w arkuszu czyta się jako „policzone i wyszło zero".
 */
export function buildRadaCsvExport(
  board: InsightsBoardResponse | undefined,
  ranking: InsightsClientsRankingResponse | undefined,
): InsightsCsvExport | null {
  // Bez KPI nie ma czego eksportować — sam ranking klientów wyszedłby pod
  // nagłówkiem obiecującym kokpit Rady.
  if (!board) return null;
  const k = board.kpis;
  const kpi: InsightsCsvExport["rows"] = [
    ["KPI", "Placementy", k.placements, "", "", "", ""],
    ["KPI", "Weryfikacje", k.verified, "", "", "", ""],
    ["KPI", "Rekomendacje", k.cv_sent, "", "", "", ""],
    ["KPI", "Interviews", k.interview, "", "", "", ""],
    ["KPI", "Efektywność lejka %", k.funnel_efficiency_pct, "", "", "", ""],
    ["KPI", "Rekrutacje zamknięte", k.jobs_closed, "", "", "", ""],
    ["KPI", "…w tym z placementem", k.jobs_closed_with_placement, "", "", "", ""],
    ["KPI", "Hit ratio %", k.hit_ratio_pct, "", "", "", ""],
    ["KPI", "Przychód miesięczny PLN", k.finance.revenue_monthly_pln, "", "", "", ""],
    ["KPI", "Koszt konsultantów PLN", k.finance.consultant_cost_monthly_pln, "", "", "", ""],
    ["KPI", "Marża miesięczna PLN", k.finance.margin_monthly_pln, "", "", "", ""],
    ["KPI", "Marża %", k.finance.margin_pct, "", "", "", ""],
    ["KPI", "Aktywni konsultanci", k.finance.active_consultants, "", "", "", ""],
    ["KPI", "Aktywne kontrakty", k.finance.active_contracts, "", "", "", ""],
    [
      "KPI",
      "Kontrakty bez stawki kandydata",
      k.finance.contracts_without_cost_leg,
      "",
      "",
      "",
      k.finance.complete ? "tak" : "nie",
    ],
  ];
  const clients: InsightsCsvExport["rows"] = (ranking?.clients ?? []).map(
    (c) => [
      "Klient",
      c.name,
      c.monthly_margin_total,
      c.head_dl_name,
      c.active_consultants,
      c.active_revenue,
      c.revenue_complete && c.margin_complete ? "tak" : "nie",
    ],
  );
  return {
    filename: "insights-rada-nadzorcza",
    headers: [
      "Sekcja",
      "Pozycja",
      "Wartość / marża miesięczna",
      "Delivery Lead",
      "Aktywni konsultanci",
      "Przychód aktywny",
      "Kwoty pełne",
    ],
    rows: [...kpi, ...clients],
  };
}
