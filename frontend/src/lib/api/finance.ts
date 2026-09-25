import api from "@/lib/api";

/** Pola liczbowe edytowalne wprost w tabeli. Lustro `EDITABLE_NUMERIC_FIELDS`
 *  ze `schemas/finance.py`. */
export type FinanceEditableField =
  | "cost_rate_md"
  | "md_count"
  | "compensation"
  | "revenue_rate_md"
  | "invoice_amount"
  | "margin_pln"
  | "margin_pct";

export interface FinancePeriod {
  year: number;
  month: number;
  label: string;
  run_id: number;
  row_count: number;
}

export interface FinanceResultRow {
  id: number;
  row_number: number;
  consultant_name: string;
  client_name: string | null;
  cost_rate_md: number | null;
  md_count: number | null;
  compensation: number | null;
  revenue_rate_md: number | null;
  invoice_amount: number | null;
  margin_pln: number | null;
  /** Surowa komórka „Marża %" z arkusza — ułamek (komórka procentowa
   *  Excela) albo punkty procentowe. Do wyświetlania służy `margin_percent`. */
  margin_pct: number | null;
  /** Marża % w punktach procentowych (21.4 = 21,4%), liczona na serwerze. */
  margin_percent: number | null;
  /** Pola zmienione ręcznie po imporcie — odróżniają „człowiek wyczyścił"
   *  od „import nie dał wartości" (to drugie dostaje ramkę „Uzupełnij"). */
  edited_fields: FinanceEditableField[];
}

export interface FinanceTotals {
  cost: number;
  revenue: number;
  /** Σ „Marża PLN" z arkusza — NIE przychód − koszt. */
  margin: number;
  /** Średnia marża % w punktach procentowych (21.4 = 21,4%). */
  avg_margin_pct: number | null;
  /** Wiersze bez „Marży PLN" (zwykle wynagrodzenie bez faktury) i ich koszt. */
  rows_without_margin: number;
  cost_without_margin: number;
}

export interface FinanceResultsResponse {
  year: number;
  month: number;
  run_id: number;
  rows: FinanceResultRow[];
  totals: FinanceTotals;
  needs_completion_count: number;
}

export interface FinanceImportRun {
  id: number;
  year: number;
  month: number;
  label: string;
  status: "current" | "superseded";
  source_filename: string;
  size_bytes: number | null;
  row_count: number;
  needs_completion_count: number;
  rejected_count: number;
  created_at: string;
  superseded_at: string | null;
  created_by_email: string | null;
}

export interface FinanceImportRejection {
  row_number: number;
  reason: string;
}

export interface FinanceImportResult {
  run_id: number;
  year: number;
  month: number;
  imported: number;
  needs_completion: number;
  rejected: number;
  rejections: FinanceImportRejection[];
  replaced_run_id: number | null;
}

/** Ciało 409 z `POST /imports`, gdy miesiąc ma już aktualną wersję. */
export interface FinancePeriodConflict {
  code: "period_exists";
  run_id: number;
  year: number;
  month: number;
  row_count: number;
  /** Ile wierszy niesie ręczne poprawki, które przepadną przy zastąpieniu. */
  edited_row_count: number;
}

/** Ciało 422, gdy arkusz nie ma wymaganych kolumn. */
export interface FinanceHeaderMismatch {
  code: "invalid_headers";
  missing: string[];
  unexpected: string[];
}

// ── Zmiany w zamówieniach ───────────────────────────────────────────────────

export type OrderTypeCode = "periodic" | "cost" | "md";
export type RateUnitCode = "hourly" | "daily" | "monthly" | "md";

/** Kto i kiedy odhaczył pozycję jako „Zrobione". */
export interface OrderItemCheck {
  by_name: string;
  at: string;
}

/** PDF zamówienia pozycji — ten sam plik co w „Zamówieniach PDF". */
export interface OrderPdfRef {
  kind: OrderPdfKind;
  id: number;
  /** Miesiąc startu „RRRR-MM" — pod nim plik stoi w „Zamówieniach PDF". */
  month: string;
  client_id: number;
  download_name: string;
}

interface OrderRef {
  order_id: number | null;
  order_group_id: number | null;
  contract_id: number | null;
  client_id: number | null;
  client_name: string;
  consultant_name: string;
  order_number: string;
  // Pola karty zamówienia (0354) — opcjonalne, bo harnessy i starsze testy
  // budują wiersze bez nich.
  /** Klucz pozycji liczony przez serwer — pod nim zapisuje się odhaczenie. */
  item_key?: string;
  order_start?: string | null;
  order_end?: string | null;
  pdf?: OrderPdfRef | null;
  done?: OrderItemCheck | null;
  entered_at?: string | null;
  entered_by?: string | null;
  entered_automatically?: boolean;
  from_order_mail?: boolean;
}

/**
 * Pozycja faktury cyklicznej Nordei zapisana przy zamówieniu (ticket 8).
 * `index` = miejsce linii w zapisie zamówienia (pod nim idzie poprawka),
 * `[brak]` w `text` = pole nieodczytane z PDF-a.
 */
export interface InvoiceLine {
  index: number;
  consultant: string | null;
  text: string;
  edited_by_name: string | null;
  edited_at: string | null;
}

/**
 * Wejście = osoba zaczynająca z nami współpracę po raz pierwszy. Kontynuacja,
 * zmiana klienta i dodatkowy projekt idą do Zmian — dlatego nie ma tu pól
 * `is_continuation` / `additional_project`.
 */
export interface OrderEntryItem extends OrderRef {
  start_date: string | null;
  end_date: string | null;
  rate_cost: number | null;
  rate_revenue: number | null;
  rate_unit: RateUnitCode | null;
  currency: string | null;
  order_type: OrderTypeCode;
  status: string;
  /** Tylko Nordea: gotowa pozycja faktury; `null`/brak = inny klient. */
  invoice_lines?: InvoiceLine[] | null;
}

/**
 * Bez „continuation": osoba pracująca dalej nie jest zejściem.
 *
 * Werdykt rozdziela dwie podzakładki o tym samym kształcie wiersza:
 * `ended_intent` → Zejścia (ktoś zapisał koniec współpracy),
 * `ending_pending` / `no_successor` → Zamówienia bez kontynuacji (klucz `ending`).
 */
export type OrderExitVerdict = "ended_intent" | "no_successor" | "ending_pending";

export interface OrderExitItem extends OrderRef {
  end_date: string;
  start_date: string | null;
  rate_cost: number | null;
  rate_revenue: number | null;
  rate_unit: RateUnitCode | null;
  currency: string | null;
  order_type: OrderTypeCode;
  verdict: OrderExitVerdict;
  verdict_label: string;
  intent: string | null;
}

export type OrderChangeKind =
  | "rate_cost"
  | "rate_revenue"
  | "end_date"
  | "additional_project"
  | "order_continuation"
  | "client_change";

export interface OrderChangeItem extends OrderRef {
  kind: OrderChangeKind;
  event_id?: number | null;
  occurred_at: string | null;
  effective_date: string | null;
  old_amount: number | null;
  new_amount: number | null;
  old_unit: RateUnitCode | null;
  new_unit: RateUnitCode | null;
  currency: string | null;
  /** Waluta STAREJ strony zmiany stawki; brak = ta sama co `currency`. */
  old_currency?: string | null;
  old_date: string | null;
  new_date: string | null;
  is_whole_order: boolean;
  source: "user" | "system" | null;
  author_name: string | null;
  rate_cost: number | null;
  rate_revenue: number | null;
  rate_unit: RateUnitCode | null;
  other_client_names: string[];
  previous_order_number: string | null;
  previous_end_date: string | null;
  previous_client_name: string | null;
  start_date: string | null;
  /** Początek współpracy z UMOWY, gdy poprzedniego zamówienia nie ma w NEXUSIE. */
  engagement_since: string | null;
}

export interface OrderGapItem extends OrderRef {
  gap_id: number;
  ended_on: string;
  detected_on: string;
  status: "open" | "filled_late";
  resolved_order_number: string | null;
  resolved_at: string | null;
  delay_days: number | null;
}

export interface OrderChangesResponse {
  period: { year: number; month: number; label: string };
  counts: {
    changes: number;
    entries: number;
    exits: number;
    ending: number;
    gaps: number;
  };
  changes: OrderChangeItem[];
  entries: OrderEntryItem[];
  exits: OrderExitItem[];
  /** Zamówienia kończące się bez kolejnego przy ŻYWEJ współpracy. */
  ending_orders: OrderExitItem[];
  gaps: OrderGapItem[];
  changes_tracked_since: string | null;
  gaps_tracked_since: string;
  open_gaps_total: number;
  /** Odhaczać mogą role Admin i Finanse (nie w „podglądzie jako"). */
  can_check?: boolean;
  /** Odhaczone pozycje, których po ponownej zmianie nie ma już w widoku. */
  superseded?: OrderSupersededCheck[];
}

export interface OrderSupersededCheck {
  item_key: string;
  tab: OrderChangesTab;
  order_id: number | null;
  order_group_id: number | null;
  summary: string;
  done: OrderItemCheck;
}

export interface OrderChangesSummary {
  period: { year: number; month: number; label: string };
  tabs: Record<OrderChangesTab, { total: number; todo: number }>;
  /** „Do zrobienia" w podzakładce Zmiany — badge przy zakładce w menu. */
  todo: number;
}

export interface OrderHistoryEntry {
  at: string;
  kind: "change" | "checked" | "unchecked";
  summary: string;
  by_name: string | null;
  automatic: boolean;
}

export type OrderChangesTab =
  | "changes"
  | "entries"
  | "exits"
  | "ending"
  | "gaps";

/** Filtry widoku. Serwer liczy je raz — dla ekranu i dla eksportu. */
export interface OrderChangesFilters {
  q?: string;
  client_id?: number | null;
  date_from?: string | null;
  date_to?: string | null;
}

function orderChangesQuery(filters: OrderChangesFilters): string {
  const params = new URLSearchParams();
  if (filters.q?.trim()) params.set("q", filters.q.trim());
  if (filters.client_id != null) params.set("client_id", String(filters.client_id));
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  const query = params.toString();
  return query ? `&${query}` : "";
}

/**
 * Eksport JEDNEJ podzakładki z aktywnymi filtrami — plik ma zawierać dokładnie
 * to, co widać na ekranie. Bez `tab` serwer zwraca cały audyt (pięć arkuszy).
 */
export function orderChangesExportPath(
  year: number,
  month: number,
  options: OrderChangesFilters & { tab?: OrderChangesTab } = {},
): string {
  const tab = options.tab ? `&tab=${options.tab}` : "";
  return (
    `/api/finance/order-changes/export?year=${year}&month=${month}` +
    tab +
    orderChangesQuery(options)
  );
}

// ── Zamówienia PDF ──────────────────────────────────────────────────────────

export interface OrderPdfMonth {
  month: string; // "RRRR-MM"
  clients: number;
  files: number;
}

export type OrderPdfKind = "order" | "group" | "amendment";
export type OrderPdfEntryType = "new" | "extension" | "amendment";

export interface OrderPdfFile {
  kind: OrderPdfKind;
  id: number;
  download_name: string;
  original_name: string;
  consultant_name: string | null;
  start: string;
  end: string | null;
  entry_type: OrderPdfEntryType;
  status: string | null;
  order_number: string | null;
  uploaded_at: string | null;
  /** Pobranie przez ZALOGOWANĄ osobę; brak = „Nowy". */
  downloaded_at?: string | null;
  /** Zamówienie ma w Zmianach tego miesiąca pozycję „Do zrobienia". */
  pending_change?: boolean;
}

export interface OrderPdfClient {
  client_id: number;
  client_name: string;
  files: OrderPdfFile[];
}

export interface OrderPdfsResponse {
  year: number;
  month: number;
  clients: OrderPdfClient[];
}

/** Ścieżka pobrania — serwer nadaje nazwę z nazwiskiem i okresem.
 *  `preview` = podgląd w panelu, który NIE liczy się jako pobranie. */
export function orderPdfFilePath(
  file: Pick<OrderPdfFile, "kind" | "id">,
  options: { preview?: boolean } = {},
): string {
  const base = `/api/finance/order-pdfs/${file.kind}/${file.id}/file`;
  return options.preview ? `${base}?preview=true` : base;
}

/**
 * ZIP z PDF-ami miesiąca: jednego klienta (`clientId`), całego miesiąca
 * (bez klienta, podfolder na klienta) albo wskazanych plików (`files`).
 */
export function orderPdfZipPath(
  year: number,
  month: number,
  options: {
    clientId?: number | null;
    files?: Array<Pick<OrderPdfFile, "kind" | "id">>;
  } = {},
): string {
  const params = new URLSearchParams({
    year: String(year),
    month: String(month),
  });
  if (options.clientId != null)
    params.set("client_id", String(options.clientId));
  if (options.files) {
    params.set(
      "files",
      options.files.map((f) => `${f.kind}:${f.id}`).join(","),
    );
  }
  return `/api/finance/order-pdfs/zip?${params.toString()}`;
}

export const financeApi = {
  listPeriods: () => api.get<FinancePeriod[]>("/api/finance/periods"),

  getResults: (params: {
    year: number;
    month: number;
    q?: string;
    sort?: string;
    direction?: "asc" | "desc";
  }) => api.get<FinanceResultsResponse>("/api/finance/results", { params }),

  updateRow: (
    rowId: number,
    payload: Partial<Record<FinanceEditableField, number | null>>,
  ) => api.patch<FinanceResultRow>(`/api/finance/results/${rowId}`, payload),

  /** Import arkusza. `replace=false` przy istniejącej wersji miesiąca kończy
   *  się 409 z `FinancePeriodConflict` — front pyta i wysyła ponownie
   *  z `replace=true`. Dwa kroki, ale plik idzie przez sieć raz. */
  importWorkbook: (
    file: File,
    year: number,
    month: number,
    replace = false,
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("year", String(year));
    fd.append("month", String(month));
    fd.append("replace", String(replace));
    return api.post<FinanceImportResult>("/api/finance/imports", fd, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },

  listImports: () => api.get<FinanceImportRun[]>("/api/finance/imports"),

  restoreImport: (runId: number) =>
    api.post<FinanceImportRun>(`/api/finance/imports/${runId}/restore`),

  getOrderChanges: (
    params: { year: number; month: number } & OrderChangesFilters,
  ) => api.get<OrderChangesResponse>("/api/finance/order-changes", { params }),

  getOrderChangesSummary: () =>
    api.get<OrderChangesSummary>("/api/finance/order-changes/summary"),

  setOrderChangeCheck: (payload: {
    year: number;
    month: number;
    item_key: string;
    done: boolean;
  }) =>
    api.post<{ item_key: string; done: OrderItemCheck | null }>(
      "/api/finance/order-changes/checks",
      payload,
    ),

  updateInvoiceLine: (orderId: number, payload: { index: number; text: string }) =>
    api.put<{ order_id: number; lines: InvoiceLine[] }>(
      `/api/finance/order-changes/invoice-lines/${orderId}`,
      payload,
    ),

  getOrderHistory: (params: {
    order_id?: number | null;
    order_group_id?: number | null;
  }) =>
    api.get<{ items: OrderHistoryEntry[] }>(
      "/api/finance/order-changes/history",
      {
        params,
      },
    ),

  getOrderPdfMonths: () =>
    api.get<{ items: OrderPdfMonth[] }>("/api/finance/order-pdfs/months"),

  getOrderPdfs: (params: { year: number; month: number }) =>
    api.get<OrderPdfsResponse>("/api/finance/order-pdfs", { params }),
};
