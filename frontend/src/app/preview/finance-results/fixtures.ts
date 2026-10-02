/**
 * Dane fikcyjne harnessu `/preview/finance-results` i lokalne odpowiedzi na
 * odczyty modułu Finanse (zamiast API).
 *
 * Osoby, firmy, numery zamówień, pliki i kwoty są zmyślone — repo jest
 * publiczne. Kafle „Wyników miesięcznych” liczy `buildResults` z tych samych
 * wierszy co tabela, tą samą regułą co serwer (kafle opisują miesiąc, nie
 * bieżące wyszukiwanie; puste wartości przy sortowaniu na końcu).
 */

import { AxiosHeaders, type AxiosResponse } from "axios";

import {
  financeApi,
  type FinanceEditableField,
  type FinanceImportRun,
  type FinancePeriod,
  type FinanceResultRow,
  type FinanceResultsResponse,
  type OrderChangeItem,
  type OrderChangesResponse,
  type OrderChangesSummary,
  type OrderHistoryEntry,
  type OrderPdfMonth,
  type OrderPdfsResponse,
} from "@/lib/api/finance";
import {
  mdConsumptionApi,
  type ImportDetail,
  type ImportLineOption,
  type ImportRow,
  type ImportSummary,
} from "@/lib/api/orderGroups";
import type { ClientRef } from "@/lib/contract-client-filter";
import { monthOptions } from "@/lib/finance-order-changes";
import type { User } from "@/store/auth";

// ── Użytkownik ──────────────────────────────────────────────────────────────

/** Fikcyjny admin: sekcja Finanse z zapisem (import, edycja komórek, MD). */
export const PREVIEW_USER: User = {
  id: 1,
  email: "podglad@finanse.example",
  name: "Administrator Przykładowy",
  role: "admin",
  roles: ["admin"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
};

// ── Wyniki miesięczne ───────────────────────────────────────────────────────

export const PERIODS: FinancePeriod[] = [
  { year: 2026, month: 9, label: "Wrzesień 2026", run_id: 41, row_count: 12 },
  { year: 2026, month: 8, label: "Sierpień 2026", run_id: 38, row_count: 11 },
  { year: 2026, month: 7, label: "Lipiec 2026", run_id: 35, row_count: 10 },
];

/** Miesiąc otwierany domyślnie — najnowszy z listy. */
export const DEFAULT_PERIOD = PERIODS[0];

interface RowSpec {
  name: string;
  client: string | null;
  costRate: number | null;
  md: number | null;
  revenueRate: number | null;
  /** Braki i ręczne poprawki — tylko wrzesień (miesiąc otwierany domyślnie). */
  september?: Partial<FinanceResultRow>;
}

const ROW_SPECS: RowSpec[] = [
  { name: "Anna Przykładowa", client: "Bank Przykładowy S.A.", costRate: 880, md: 21, revenueRate: 1150 },
  { name: "Bartosz Testowy", client: "Bank Przykładowy S.A.", costRate: 960, md: 20, revenueRate: 1240 },
  { name: "Celina Makietowa", client: "Telekom Demo", costRate: 800, md: 22, revenueRate: 1000 },
  // Marża ujemna: stawka przychodowa niższa niż kosztowa.
  { name: "Damian Fikcyjny", client: "Telekom Demo", costRate: 1040, md: 18, revenueRate: 980 },
  // Import nie dał stawki kosztowej — jedna komórka „brak danych”.
  {
    name: "Ewa Wzorcowa",
    client: "Ubezpieczenia Wzorcowe S.A.",
    costRate: 760,
    md: 21,
    revenueRate: 990,
    september: { cost_rate_md: null },
  },
  // Wynagrodzenie bez faktury: brak stawki przychodowej, faktury i marży.
  {
    name: "Filip Demonstracyjny",
    client: "Ubezpieczenia Wzorcowe S.A.",
    costRate: 900,
    md: 21,
    revenueRate: 1180,
    september: {
      revenue_rate_md: null,
      invoice_amount: null,
      margin_pln: null,
      margin_pct: null,
      margin_percent: null,
    },
  },
  { name: "Grażyna Próbna", client: "Energia Demo Sp. z o.o.", costRate: 1120, md: 19, revenueRate: 1400 },
  // Arkusz bez liczby MD — kwoty są, ilość do uzupełnienia.
  {
    name: "Hubert Zmyślony",
    client: "Energia Demo Sp. z o.o.",
    costRate: 850,
    md: 20,
    revenueRate: 1075,
    september: { md_count: null },
  },
  { name: "Iwona Szablonowa", client: "Logistyka Przykładowa", costRate: 700, md: 22, revenueRate: 690 },
  { name: "Jakub Atrapa", client: null, costRate: 920, md: 20, revenueRate: 1180 },
  // Marża poprawiona ręcznie po imporcie.
  {
    name: "Kinga Modelowa",
    client: "Bank Przykładowy S.A.",
    costRate: 1000,
    md: 21,
    revenueRate: 1300,
    september: {
      margin_pln: 5000,
      margin_pct: 0.1832,
      margin_percent: 18.3,
      edited_fields: ["margin_pln", "margin_pct"],
    },
  },
  // Stawka wyczyszczona przez człowieka — puste pole bez „Uzupełnij”.
  {
    name: "Leon Pokazowy",
    client: "Telekom Demo",
    costRate: 840,
    md: 10.5,
    revenueRate: 1100,
    september: { revenue_rate_md: null, edited_fields: ["revenue_rate_md"] },
  },
];

function round(value: number, digits: number): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function buildRow(
  runId: number,
  index: number,
  spec: RowSpec,
  mdShift: number,
  withGaps: boolean,
): FinanceResultRow {
  const md = spec.md == null ? null : spec.md + mdShift;
  const compensation = spec.costRate != null && md != null ? spec.costRate * md : null;
  const invoice = spec.revenueRate != null && md != null ? spec.revenueRate * md : null;
  const margin = compensation != null && invoice != null ? invoice - compensation : null;
  return {
    id: runId * 100 + index + 1,
    row_number: index + 2,
    consultant_name: spec.name,
    client_name: spec.client,
    cost_rate_md: spec.costRate,
    md_count: md,
    compensation,
    revenue_rate_md: spec.revenueRate,
    invoice_amount: invoice,
    margin_pln: margin,
    margin_pct: margin != null && invoice ? round(margin / invoice, 4) : null,
    margin_percent: margin != null && invoice ? round((margin / invoice) * 100, 1) : null,
    edited_fields: [],
    ...(withGaps ? spec.september : undefined),
  };
}

/** Wiersze miesiąca; starsze miesiące mają komplet danych i mniej osób. */
function monthRows(period: FinancePeriod): FinanceResultRow[] {
  const september = period.month === 9;
  const mdShift = period.month === 9 ? 0 : period.month === 8 ? -1 : 1;
  return ROW_SPECS.slice(0, period.row_count).map((spec, index) =>
    buildRow(period.run_id, index, spec, mdShift, september),
  );
}

const EDITABLE_FIELDS: FinanceEditableField[] = [
  "cost_rate_md",
  "md_count",
  "compensation",
  "revenue_rate_md",
  "invoice_amount",
  "margin_pln",
  "margin_pct",
];

function needsCompletion(row: FinanceResultRow): boolean {
  return EDITABLE_FIELDS.some(
    (field) => row[field] == null && !row.edited_fields.includes(field),
  );
}

function sum(values: Array<number | null>): number {
  return round(
    values.reduce<number>((total, value) => total + (value ?? 0), 0),
    2,
  );
}

function sortValue(row: FinanceResultRow, sort: string): number | null {
  if (sort === "margin_pct") return row.margin_percent;
  const field = EDITABLE_FIELDS.find((candidate) => candidate === sort);
  return field ? row[field] : row.row_number;
}

/** Odpowiedź `GET /api/finance/results` policzona lokalnie. */
export function buildResults(params: {
  year: number;
  month: number;
  q?: string;
  sort?: string;
  direction?: "asc" | "desc";
}): FinanceResultsResponse | null {
  const period = PERIODS.find((p) => p.year === params.year && p.month === params.month);
  if (!period) return null;
  const all = monthRows(period);

  const needle = (params.q ?? "").trim().toLowerCase();
  const visible = needle
    ? all.filter(
        (row) =>
          row.consultant_name.toLowerCase().includes(needle) ||
          (row.client_name ?? "").toLowerCase().includes(needle),
      )
    : all;

  const sort = params.sort ?? "row_number";
  const sign = params.direction === "desc" ? -1 : 1;
  const present = visible.filter((row) => sortValue(row, sort) != null);
  const missing = visible.filter((row) => sortValue(row, sort) == null);
  present.sort(
    (a, b) =>
      ((sortValue(a, sort) ?? 0) - (sortValue(b, sort) ?? 0)) * sign ||
      a.row_number - b.row_number,
  );

  const revenue = sum(all.map((row) => row.invoice_amount));
  const margin = sum(all.map((row) => row.margin_pln));
  const withoutMargin = all.filter((row) => row.margin_pln == null);
  return {
    year: period.year,
    month: period.month,
    run_id: period.run_id,
    rows: [...present, ...missing],
    totals: {
      cost: sum(all.map((row) => row.compensation)),
      revenue,
      margin,
      avg_margin_pct: revenue ? round((margin / revenue) * 100, 1) : null,
      rows_without_margin: withoutMargin.length,
      cost_without_margin: sum(withoutMargin.map((row) => row.compensation)),
    },
    needs_completion_count: all.filter(needsCompletion).length,
  };
}

// ── Archiwum ────────────────────────────────────────────────────────────────

export const IMPORT_RUNS: FinanceImportRun[] = [
  {
    id: 41,
    year: 2026,
    month: 9,
    label: "Wrzesień 2026",
    status: "current",
    source_filename: "wyniki_2026-09_korekta.xlsx",
    size_bytes: 48_210,
    row_count: 12,
    needs_completion_count: 3,
    rejected_count: 1,
    created_at: "2026-10-01T08:14:00Z",
    superseded_at: null,
    created_by_email: "olga.wzorcowa@finanse.example",
  },
  {
    id: 40,
    year: 2026,
    month: 9,
    label: "Wrzesień 2026",
    status: "superseded",
    source_filename: "wyniki_2026-09.xlsx",
    size_bytes: 47_530,
    row_count: 11,
    needs_completion_count: 5,
    rejected_count: 3,
    created_at: "2026-09-30T15:42:00Z",
    superseded_at: "2026-10-01T08:14:00Z",
    created_by_email: "olga.wzorcowa@finanse.example",
  },
  {
    id: 38,
    year: 2026,
    month: 8,
    label: "Sierpień 2026",
    status: "current",
    source_filename: "wyniki_2026-08.xlsx",
    size_bytes: 1_258_300,
    row_count: 11,
    needs_completion_count: 0,
    rejected_count: 0,
    created_at: "2026-09-02T09:05:00Z",
    superseded_at: null,
    created_by_email: "olga.wzorcowa@finanse.example",
  },
  {
    id: 35,
    year: 2026,
    month: 7,
    label: "Lipiec 2026",
    status: "current",
    source_filename: "wyniki_lipiec_zestawienie_miesieczne_kontraktorow.xlsx",
    size_bytes: 44_980,
    row_count: 10,
    needs_completion_count: 0,
    rejected_count: 0,
    created_at: "2026-08-03T10:31:00Z",
    superseded_at: null,
    created_by_email: null,
  },
];

// ── Import zużycia MD ───────────────────────────────────────────────────────

function option(
  orderId: number,
  orderNumber: string,
  clientId: number,
  clientName: string,
  consultant: string,
  mdRemaining: number | null,
): ImportLineOption {
  return {
    order_id: orderId,
    order_number: orderNumber,
    client_id: clientId,
    client_name: clientName,
    consultant_name: consultant,
    md_remaining: mdRemaining,
  };
}

function importRow(overrides: Partial<ImportRow> & Pick<ImportRow, "id">): ImportRow {
  return {
    row_number: overrides.id,
    consultant_name: "Anna Przykładowa",
    md_reported: 21,
    status: "applied",
    status_label: "Zaktualizowano",
    matched_order_id: null,
    matched: null,
    options: [],
    resolved_at: null,
    status_reason: null,
    overflow_md: null,
    merged_rows: 1,
    notes_raw: null,
    order_number_hint: null,
    invoice_amount: null,
    cost_status: null,
    cost_status_label: null,
    ...overrides,
  };
}

const SEPTEMBER_MD_ROWS: ImportRow[] = [
  importRow({
    id: 2,
    consultant_name: "Anna Przykładowa",
    md_reported: 21,
    invoice_amount: 24_150,
    matched_order_id: 5011,
    matched: option(5011, "4599050001", 11, "Bank Przykładowy S.A.", "Anna Przykładowa", 22),
  }),
  importRow({
    id: 3,
    consultant_name: "Bartosz Testowy",
    md_reported: 18.5,
    invoice_amount: 22_940,
    merged_rows: 2,
    order_number_hint: "4599050001",
    matched_order_id: 5012,
    matched: option(5012, "4599050001", 11, "Bank Przykładowy S.A.", "Bartosz Testowy", 41.5),
  }),
  // Dwa zamówienia tej samej osoby — system nie wybiera za człowieka.
  importRow({
    id: 4,
    consultant_name: "Celina Makietowa",
    md_reported: 20,
    invoice_amount: 20_000,
    status: "needs_assignment",
    status_label: "Wymaga przypisania",
    options: [
      option(5021, "4599060004", 12, "Telekom Demo", "Celina Makietowa", 34),
      option(5027, "4599060011", 12, "Telekom Demo", "Celina Makietowa", 60),
    ],
  }),
  // Zejście przekroczyłoby pulę — czeka na zatwierdzenie.
  importRow({
    id: 5,
    consultant_name: "Damian Fikcyjny",
    md_reported: 22,
    invoice_amount: 21_560,
    status: "overflow",
    status_label: "Do weryfikacji – przekroczenie puli o 7 MD",
    overflow_md: 7,
    matched_order_id: 5022,
    matched: option(5022, "4599060004", 12, "Telekom Demo", "Damian Fikcyjny", 15),
  }),
  // Numer z „Uwag”, którego nie ma w systemie.
  importRow({
    id: 6,
    consultant_name: "Ewa Wzorcowa",
    md_reported: 21,
    invoice_amount: 20_790,
    status: "unmatched",
    status_label: "Brak pasującego zamówienia",
    notes_raw: "zam. 4599059999",
    order_number_hint: "4599059999",
    status_reason:
      "Zamówienia nr 4599059999 nie ma w NEXUSIE. Zużycie nie trafiło na żadne inne " +
      "zamówienie tej osoby — dodaj zamówienie albo popraw numer w arkuszu.",
  }),
  // Zamówienie kosztowe: faktura zeszła z budżetu, MD nie ma czego zdejmować.
  importRow({
    id: 7,
    consultant_name: "Grażyna Próbna",
    md_reported: 19,
    invoice_amount: 26_600,
    status: "unmatched",
    status_label: "Rozliczono kwotowo",
    notes_raw: "zlecenie 4599070002",
    order_number_hint: "4599070002",
    cost_status: "applied",
    cost_status_label: "Rozliczono",
  }),
  // Zwykły kontraktor okresowy — bez zamówienia MD, to nie błąd.
  importRow({
    id: 8,
    consultant_name: "Iwona Szablonowa",
    md_reported: 22,
    invoice_amount: 15_180,
    status: "unmatched",
    status_label: "Bez zamówienia MD",
  }),
  importRow({
    id: 9,
    consultant_name: "Kinga Modelowa",
    md_reported: 21,
    invoice_amount: 27_300,
    matched_order_id: 5013,
    matched: option(5013, "4599050007", 11, "Bank Przykładowy S.A.", "Kinga Modelowa", 9),
  }),
];

const AUGUST_MD_ROWS: ImportRow[] = [
  importRow({
    id: 2,
    consultant_name: "Anna Przykładowa",
    md_reported: 20,
    invoice_amount: 23_000,
    matched_order_id: 5011,
    matched: option(5011, "4599050001", 11, "Bank Przykładowy S.A.", "Anna Przykładowa", 43),
  }),
  importRow({
    id: 3,
    consultant_name: "Bartosz Testowy",
    md_reported: 19,
    invoice_amount: 23_560,
    matched_order_id: 5012,
    matched: option(5012, "4599050001", 11, "Bank Przykładowy S.A.", "Bartosz Testowy", 60),
  }),
  importRow({
    id: 4,
    consultant_name: "Damian Fikcyjny",
    md_reported: 17,
    invoice_amount: 16_660,
    matched_order_id: 5022,
    matched: option(5022, "4599060004", 12, "Telekom Demo", "Damian Fikcyjny", 37),
  }),
];

function importSummary(
  id: number,
  periodMonth: string,
  filename: string,
  createdAt: string,
  rows: ImportRow[],
): ImportSummary {
  const pending = rows.filter(
    (row) => row.status === "needs_assignment" || row.status === "overflow",
  ).length;
  const applied = rows.filter((row) => row.status === "applied").length;
  return {
    id,
    period_month: periodMonth,
    filename,
    rows_total: rows.length,
    rows_applied: applied,
    rows_ambiguous: pending,
    rows_unmatched: rows.length - applied - pending,
    rows_cost_applied: rows.filter((row) => row.cost_status === "applied").length,
    rows_cost_unmatched: 0,
    uploaded_by_user_id: PREVIEW_USER.id,
    created_at: createdAt,
  };
}

export const MD_IMPORT_DETAILS: ImportDetail[] = [
  {
    ...importSummary(71, "2026-09", "raport_md_2026-09.xlsx", "2026-10-01T09:20:00Z", SEPTEMBER_MD_ROWS),
    rows: SEPTEMBER_MD_ROWS,
    skipped_rows: [
      { row: 14, reason: "brak liczby MD", consultant_name: "Leon Pokazowy" },
    ],
    sheet_name: "Wrzesień",
  },
  {
    ...importSummary(64, "2026-08", "raport_md_2026-08.xlsx", "2026-09-02T09:40:00Z", AUGUST_MD_ROWS),
    rows: AUGUST_MD_ROWS,
    skipped_rows: [],
    sheet_name: "Sierpień",
  },
];

/** Lista „Ostatnie importy” — podsumowania bez wierszy. */
export const MD_IMPORTS: ImportSummary[] = MD_IMPORT_DETAILS.map((detail) => ({
  id: detail.id,
  period_month: detail.period_month,
  filename: detail.filename,
  rows_total: detail.rows_total,
  rows_applied: detail.rows_applied,
  rows_ambiguous: detail.rows_ambiguous,
  rows_unmatched: detail.rows_unmatched,
  rows_cost_applied: detail.rows_cost_applied,
  rows_cost_unmatched: detail.rows_cost_unmatched,
  uploaded_by_user_id: detail.uploaded_by_user_id,
  created_at: detail.created_at,
}));

// ── Pozostałe zakładki (mają własne harnessy — tu minimum) ──────────────────

export const CLIENTS_LOOKUP: ClientRef[] = [
  { id: 11, name: "Bank Przykładowy S.A." },
  { id: 12, name: "Telekom Demo" },
];

export const ORDER_PDF_MONTHS: OrderPdfMonth[] = [];

/** Bieżący miesiąc tak, jak wybiera go zakładka „Zmiany w zamówieniach”. */
export function currentOrderChangesMonth(today: Date): {
  year: number;
  month: number;
  label: string;
} {
  const option = monthOptions(today)[1];
  return { year: option.year, month: option.month, label: option.label };
}

function changeItem(
  orderId: number,
  consultant: string,
  clientId: number,
  client: string,
  orderNumber: string,
  day: string,
  overrides: Partial<OrderChangeItem>,
): OrderChangeItem {
  return {
    order_id: orderId,
    order_group_id: null,
    contract_id: orderId + 100,
    client_id: clientId,
    client_name: client,
    consultant_name: consultant,
    order_number: orderNumber,
    item_key: `chg:ev:${orderId}`,
    order_start: day,
    order_end: null,
    // Bez PDF-u: podgląd pliku szedłby do API natywnym `fetch`.
    pdf: null,
    done: null,
    entered_at: `${day}T08:10:00Z`,
    entered_by: "Olga Wzorcowa",
    entered_automatically: false,
    from_order_mail: false,
    kind: "rate_revenue",
    event_id: orderId,
    occurred_at: `${day}T08:10:00Z`,
    effective_date: day,
    old_amount: null,
    new_amount: null,
    old_unit: null,
    new_unit: null,
    currency: "PLN",
    old_date: null,
    new_date: null,
    is_whole_order: false,
    source: "user",
    author_name: "Olga Wzorcowa",
    rate_cost: null,
    rate_revenue: null,
    rate_unit: null,
    other_client_names: [],
    previous_order_number: null,
    previous_end_date: null,
    previous_client_name: null,
    start_date: null,
    engagement_since: null,
    ...overrides,
  };
}

/** Odpowiedź `GET /api/finance/order-changes`: dwie zmiany w bieżącym miesiącu. */
export function buildOrderChanges(
  year: number,
  month: number,
  today: Date,
): OrderChangesResponse {
  const current = currentOrderChangesMonth(today);
  const isCurrent = current.year === year && current.month === month;
  const day = `${year}-${String(month).padStart(2, "0")}-01`;
  const changes = isCurrent
    ? [
        changeItem(9101, "Anna Przykładowa", 11, "Bank Przykładowy S.A.", "4599050001", day, {
          kind: "rate_revenue",
          old_amount: 1150,
          new_amount: 1210,
          old_unit: "md",
          new_unit: "md",
        }),
        changeItem(9102, "Celina Makietowa", 12, "Telekom Demo", "4599060004", day, {
          kind: "rate_cost",
          old_amount: 800,
          new_amount: 840,
          old_unit: "md",
          new_unit: "md",
        }),
      ]
    : [];
  const label =
    monthOptions(today).find((o) => o.year === year && o.month === month)?.label ??
    `${year}-${String(month).padStart(2, "0")}`;
  return {
    period: { year, month, label },
    counts: { changes: changes.length, entries: 0, exits: 0, ending: 0, gaps: 0 },
    changes,
    entries: [],
    exits: [],
    ending_orders: [],
    gaps: [],
    changes_tracked_since: "2026-09-01T00:00:00Z",
    gaps_tracked_since: "2026-08-01",
    open_gaps_total: 0,
    can_check: true,
    superseded: [],
  };
}

export function buildOrderChangesSummary(today: Date): OrderChangesSummary {
  const current = currentOrderChangesMonth(today);
  const total = buildOrderChanges(current.year, current.month, today).changes.length;
  const empty = { total: 0, todo: 0 };
  return {
    period: current,
    tabs: {
      changes: { total, todo: total },
      entries: empty,
      exits: empty,
      ending: empty,
      gaps: empty,
    },
    todo: total,
  };
}

const ORDER_HISTORY: OrderHistoryEntry[] = [
  {
    at: "2026-06-02T09:00:00Z",
    kind: "change",
    summary: "Zamówienie wprowadzone do systemu",
    by_name: "Olga Wzorcowa",
    automatic: false,
  },
];

// ── Lokalne odpowiedzi zamiast API ──────────────────────────────────────────

function ok<T>(data: T): Promise<AxiosResponse<T>> {
  const response: AxiosResponse<T> = {
    data,
    status: 200,
    statusText: "OK",
    headers: {},
    config: { headers: new AxiosHeaders() },
  };
  return Promise.resolve(response);
}

function notFound(what: string): Promise<never> {
  return Promise.reject(new Error(`podgląd: brak danych (${what})`));
}

/**
 * Podmienia ODCZYTY `financeApi` i `mdConsumptionApi` na lokalne odpowiedzi
 * z danych powyżej i zwraca funkcję, która przywraca oryginały.
 *
 * Bez tego nie da się pokazać wybranego importu MD (komponent trzyma go
 * w stanie i pobiera kliknięciem, poza react-query) ani sortowania i szukania
 * w wynikach (każda zmiana to nowy klucz zapytania). Zapisy zostają oryginalne
 * — odcina je interceptor harnessu i blokada z `preview/layout.tsx`.
 */
export function installLocalFinanceBackend(): () => void {
  const originalFinance = { ...financeApi };
  const originalMd = { ...mdConsumptionApi };

  const financeReads: Partial<typeof financeApi> = {
    listPeriods: () => ok(PERIODS),
    getResults: (params) => {
      const results = buildResults(params);
      return results ? ok(results) : notFound("wyniki za ten miesiąc");
    },
    listImports: () => ok(IMPORT_RUNS),
    getOrderChanges: (params) =>
      ok(buildOrderChanges(params.year, params.month, new Date())),
    getOrderChangesSummary: () => ok(buildOrderChangesSummary(new Date())),
    getOrderHistory: () => ok({ items: ORDER_HISTORY }),
    getOrderPdfMonths: () => ok({ items: ORDER_PDF_MONTHS }),
    getOrderPdfs: (params): Promise<AxiosResponse<OrderPdfsResponse>> =>
      ok({ year: params.year, month: params.month, clients: [] }),
  };
  const mdReads: Partial<typeof mdConsumptionApi> = {
    listImports: () => ok({ imports: MD_IMPORTS }),
    getImport: (importId) => {
      const detail = MD_IMPORT_DETAILS.find((item) => item.id === importId);
      return detail ? ok(detail) : notFound("import MD");
    },
  };

  Object.assign(financeApi, financeReads);
  Object.assign(mdConsumptionApi, mdReads);
  return () => {
    Object.assign(financeApi, originalFinance);
    Object.assign(mdConsumptionApi, originalMd);
  };
}
