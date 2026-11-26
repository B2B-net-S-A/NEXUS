/**
 * Fikcyjne odpowiedzi ekranów lekcji nowości — obszar: contracts.
 * Zasady jak w `lesson-screens.ts`: dane wymyślone (repo publiczne), typy z aplikacji,
 * klucz = ścieżka API bez query.
 */
import type { B2BRole } from "../../src/lib/api";
import type { DocumentItem, DocumentTypeDef, DocumentTypesResponse } from "../../src/lib/api/b2bDocuments";
import type { Forecast, MarginRow, MarginTotals, UtilizationData } from "../../src/lib/contract-analytics";

/** Typ aneksu bez pól — kafel w kroku „typ” kreatora potrzebuje tylko nazwy i rodziny. */
const ANNEX = (key: string, label: string, description: string): DocumentTypeDef => ({
  key,
  label,
  family: "annex",
  languages: ["pl"],
  parent: "b2b",
  fields: [],
  effect_label: "",
  description,
  signatories: "both",
  uses_refs: false,
  allows_external: true,
  legacy_languages: [],
});

/**
 * Generator umów B2B → „Nowy aneks” (lekcja „Aneks z własną nazwą”): katalog
 * typów aneksów czyta `/api/b2b-generator/document-types`. Bez niego kreator
 * pokazuje „Nie udało się wczytać typów aneksów” i kafla z zadania nie ma.
 */
const DOCUMENT_TYPES: DocumentTypesResponse = {
  types: [
    ANNEX("annex_rate", "Aneks — zmiana stawki", "Nowa stawka od wskazanej daty."),
    ANNEX("annex_custom", "Aneks — inna zmiana", "Zmiana spoza listy, z własną nazwą aneksu."),
  ],
  ref_labels: {},
  ref_defaults: {},
  mandate_forms: [],
  custom_types: [],
};

/**
 * Analityka kontraktów (lekcja „Analityka kontraktów”): kwoty czyta
 * `/api/contract-analytics/*`, nie zestaw Poligonu. Bez wiersza klienta tabela
 * „Kto ile przynosi” nie ma nagłówka „Marża” z pokazu. Kwoty jak kontrakt
 * ćwiczebny Filipa Bukowca w Banku Północnym: 122 zł/h − 105 zł/h × 168 h.
 */
const MARGIN_TOTALS: MarginTotals = {
  clients: 1,
  active_contracts: 1,
  total_monthly_revenue: 20496,
  total_monthly_margin: 2856,
  margin_pct: 13.9,
  fx_missing: false,
};
const MARGIN_BY_CLIENT: MarginRow[] = [
  {
    client_id: 990501,
    client_name: "Bank Północny",
    active_contracts: 1,
    total_monthly_margin: 2856,
    total_monthly_revenue: 20496,
    margin_pct: 13.9,
  },
];
const MARGIN_BY_CONTRACTOR: MarginRow[] = [
  {
    candidate_id: 990112,
    candidate_name: "Filip Bukowiec",
    active_contracts: 1,
    total_monthly_margin: 2856,
    total_monthly_revenue: 20496,
    margin_pct: 13.9,
  },
];
const UTILIZATION: UtilizationData = {
  total_candidates: 2,
  candidates_active: 1,
  active_contracts: 1,
  candidates_on_bench: 1,
  utilization_pct: 50,
  avg_bench_days: 12,
};
const FORECAST: Forecast = {
  horizon_months: 2,
  months: [
    { month: "2026-12", month_label: "grudzień 2026", revenue: 20496, margin: 2856, active_count: 1 },
    { month: "2027-01", month_label: "styczeń 2027", revenue: 2928, margin: 408, active_count: 1 },
  ],
};

export const SCREENS_CONTRACTS: Record<string, unknown> = {
  "/api/b2b-generator/document-types": DOCUMENT_TYPES,
  // Rejestr aneksów i umów pusty: lekcja patrzy tylko na kreator.
  "/api/b2b-generator/documents": [] satisfies DocumentItem[],
  "/api/b2b-generator/generated": [],
  "/api/b2b-generator/roles": [] satisfies B2BRole[],
  "/api/b2b-generator/next-number": { contract_number: "B2B/990001/2026", year: 2026, seq: 990001 },
  "/api/contract-analytics/margin-totals": MARGIN_TOTALS,
  "/api/contract-analytics/margin-by-client": MARGIN_BY_CLIENT,
  "/api/contract-analytics/margin-by-contractor": MARGIN_BY_CONTRACTOR,
  "/api/contract-analytics/utilization": UTILIZATION,
  "/api/contract-analytics/revenue-forecast": FORECAST,
};
