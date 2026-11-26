/**
 * Fikcyjne odpowiedzi ekranów lekcji nowości — obszar: finance.
 * Zasady jak w `lesson-screens.ts`: dane wymyślone (repo publiczne), typy z aplikacji,
 * klucz = ścieżka API bez query.
 *
 * Widoki Finansów (Przebieg miesiąca, Rozliczenia klientów, Faktury do klientów)
 * nie należą do zestawu Poligonu, więc na produkcji czytają prawdziwe API, a w
 * `lessons-solo.spec.ts` bez tych odpowiedzi pokazywały błąd zamiast kotwic lekcji.
 * Jeden klient („Bank Północny”) i dwie osoby z fikcji Poligonu.
 *
 * Identyfikatory celowo poniżej 990000: Poligon bierze każde żądanie z numerem
 * 990000+ (`mentionsPoligon` w `src/lib/poligon/store.ts`) ze swojego zestawu,
 * a tych widoków tam nie ma („Tego ekranu nie ma jeszcze na poligonie”). Na
 * produkcji Rozliczenia pokazują prawdziwych klientów, więc ich odczyty idą do API.
 */
import type {
  ClientAcceptanceMonth,
  ClientDocumentsMonth,
  ClientRules,
  MonthCheckView,
  MonthCloseOverview,
  MonthCloseStages,
  SettlementClient,
  SettlementDetail,
  SettlementMonth,
  SettlementRow,
  TeamMonth,
} from "../../src/lib/api/client-settlements";
import type { OverdueInvoices } from "../../src/lib/api/client-invoicing";
import type { CasesMonth } from "../../src/lib/api/settlement-cases";
import type { ReminderOverview } from "../../src/lib/api/settlement-reminders";

const CLIENT_ID = 980501;
const FILIP = 980521;
const MAJA = 980522;
const CLIENT_NAME = "Bank Północny";
const MONTH = "2026-11";

/** Dwie osoby klienta: jedna bez uwag, jedna z uwagą do decyzji. */
const STAGES: MonthCloseStages = {
  people: 2,
  report: { in: 2, missing: 0, md_auto: 2, md_manual: 0 },
  check: { clean: 1, auto_clean: 1, resolved: 0, warn: 1, fail: 0, returned: 0, unread: 0, no_md: 0, missing: 0 },
  accept: { done: 1, auto: 1, ready: 0 },
  contractor_invoice: { match: 1, differs: 0, nip: 0, can_issue: 0, none: 0, waiting: 1 },
  client_invoice: { issued: 0, ready: 1, waiting_client: 0, waiting: 1, issued_early: 0 },
  missing_order: 0,
};

/** „Przebieg miesiąca”: jeden klient z dwiema osobami i jedna uwaga w „Błędach i uwagach”. */
const MONTH_CLOSE: MonthCloseOverview = {
  month: MONTH,
  can_see_amounts: false,
  totals: {
    people: 2,
    clean: 1,
    accepted: 1,
    decide: 1,
    unread: 0,
    missing: 0,
    contractor_in_ksef: 1,
    client_invoice_issued: 0,
  },
  stages: STAGES,
  clients: [
    {
      client_id: CLIENT_ID,
      name: CLIENT_NAME,
      people: 2,
      clean: 1,
      accepted: 1,
      decide: 1,
      unread: 0,
      missing: 0,
      contractor_in_ksef: 1,
      client_invoice_issued: 0,
      client_invoice_ready: 1,
      revenue_ready: null,
      top_reason: "Akceptacja bez liczby godzin",
      client_report: null,
      auto_accept: null,
      stages: STAGES,
    },
  ],
  reasons: [
    {
      key: "acc.hours_present",
      title: "Akceptacja bez liczby godzin",
      level: "warn",
      count: 1,
      clients: [{ client_id: CLIENT_ID, name: CLIENT_NAME, count: 1 }],
      people: [{ contract_id: MAJA, person: "Maja Wierzbicka", client_id: CLIENT_ID }],
    },
  ],
};

const TEAM: TeamMonth = { month: MONTH, people: [] };

const REMINDERS: ReminderOverview = {
  enabled: false,
  portal_state: "off",
  month: MONTH,
  schedule: {},
  settlements_address: null,
  clients: [],
};

/** Kontrola miesiąca: jedna otwarta rozbieżność godzin (bez kwot). */
const MONTH_CHECK: MonthCheckView = {
  month: MONTH,
  checked_at: "2026-11-25T06:00:00+00:00",
  waits_until: "2026-12-15",
  summary: {
    person_months: 2,
    matched: 1,
    skipped: {},
    overtime_confirmed: 0,
    cases: 1,
    cases_amount: null,
    open: 1,
    open_amount: null,
    by_state: { new: 1, to_correct: 0, explained: 0, closed: 0 },
    by_kind: { hours_mismatch: 1, cost_without_sale: 0, sale_without_cost: 0, over_working_days: 0 },
  },
  cases: [
    {
      id: 980801,
      kind: "hours_mismatch",
      kind_label: "Różne godziny",
      month: MONTH,
      candidate_id: 980601,
      person: "Maja Wierzbicka",
      contract_id: MAJA,
      client_id: CLIENT_ID,
      client: CLIENT_NAME,
      amount: null,
      currency: "PLN",
      data_issue: null,
      data_issue_label: null,
      details: { client_hours: "160", contractor_hours: "168" },
      state: "new",
      reason: null,
      decided_at: null,
      first_seen_at: "2026-11-25T06:00:00+00:00",
      closed_at: null,
    },
  ],
  amounts: false,
};

const SETTLEMENT_CLIENTS: SettlementClient[] = [
  { client_id: CLIENT_ID, name: CLIENT_NAME, active_contracts: 2, rules_set: true, todo: 1 },
];

const ROW = (contractId: number, person: string, status: SettlementRow["status"]): SettlementRow => ({
  contract_id: contractId,
  settlement_id: contractId + 1000,
  person,
  order_number: `ZAM/${contractId}`,
  status,
  issues: status === "warnings" ? "Akceptacja bez liczby godzin" : null,
  issue_level: status === "warnings" ? "warn" : null,
  md_source: "rcp",
  md_regular: "20",
  md_extra: null,
  md_charged: "20",
  md_remaining_after: null,
  amount_cost: null,
  amount_revenue: null,
  margin: null,
  margin_pct: null,
  contractor_invoice: status === "accepted" ? "in_ksef" : "none",
  client_invoice: status === "accepted" ? "ready" : "waiting",
});

/** Lista osób klienta w miesiącu (rozwinięcie w „Przebiegu miesiąca” i „RCP i faktury kontraktorów”). */
const SETTLEMENT_MONTH: SettlementMonth = {
  client_id: CLIENT_ID,
  client_name: CLIENT_NAME,
  month: MONTH,
  can_see_amounts: false,
  counts: { todo: 1, missing: 0, needs_fix: 0, accepted: 1, all: 2 },
  batch_ready: 0,
  auto_accept: null,
  rows: [ROW(FILIP, "Filip Bukowiec", "accepted"), ROW(MAJA, "Maja Wierzbicka", "warnings")],
};

/** Karta osoby (wiersz listy po kliknięciu nazwiska) z sekcją „Dodatki do faktury”, bez dodatków. */
const DETAIL = (row: SettlementRow): SettlementDetail => ({
  contract_id: row.contract_id,
  settlement_id: row.settlement_id,
  kind: "actual",
  estimate: null,
  person: row.person,
  client_name: CLIENT_NAME,
  month: MONTH,
  order_number: row.order_number,
  contract_number: null,
  status: row.status,
  fix_reason: null,
  accepted_at: row.status === "accepted" ? "2026-11-24T08:00:00+00:00" : null,
  accepted_auto: row.status === "accepted",
  documents: [],
  md_regular: row.md_regular,
  md_extra: null,
  md_source: "rcp",
  lines: [],
  total_md: row.md_regular,
  total_net: null,
  checks: [],
  order: null,
  extras: {
    items: [],
    approved_total: null,
    pending_total: null,
    pending_count: 0,
    kinds: [
      { key: "referral", label: "Premia za polecenie" },
      { key: "training", label: "Szkolenie" },
    ],
  },
});

/** Klient bez akceptacji po wysyłce KCP i bez dokumentu na projekt: oba panele nad listą się chowają. */
const CLIENT_ACCEPTANCE: ClientAcceptanceMonth = { enabled: false, client_id: CLIENT_ID, month: MONTH };
const CLIENT_DOCUMENTS: ClientDocumentsMonth = {
  client_id: CLIENT_ID,
  month: MONTH,
  enabled: false,
  kind: "",
  stage: null,
  can_see_amounts: false,
  projects: [],
  skipped: [],
};

/** Reguły klienta z sekcją „Faktura do klienta” (kotwica lekcji). */
const CLIENT_RULES: ClientRules = {
  client_id: CLIENT_ID,
  client_name: CLIENT_NAME,
  effective_from: "2026-10",
  sections: [
    {
      key: "client_invoice",
      title: "Faktura do klienta",
      rules: [
        {
          key: "cl.overtime_item",
          name: "Nadgodziny osobną pozycją",
          level: "off",
          params: { suffix: "_nadgodziny" },
          param_fields: [{ key: "suffix", label: "przyrostek", suffix: null }],
          hint: null,
        },
      ],
    },
  ],
};

/** „Sprawy”: jedna zaległa sprawa po stronie konsultanta. */
const CASES: CasesMonth = {
  month: MONTH,
  today: "2026-11-26",
  counts: { all: 1, overdue: 1, consultant: 1, client: 0, dl: 0, finance: 0 },
  clients: [{ client_id: CLIENT_ID, name: CLIENT_NAME, count: 1 }],
  cases: [
    {
      key: `${MAJA}-${MONTH}`,
      settlement_id: MAJA + 1000,
      contract_id: MAJA,
      client_id: CLIENT_ID,
      client_name: CLIENT_NAME,
      person: "Maja Wierzbicka",
      month: MONTH,
      status: "warnings",
      actor: "consultant",
      actor_label: "Konsultant",
      reasons: [{ code: "acc.hours_present", title: "Akceptacja bez liczby godzin", detail: null }],
      recipient: null,
      day0: "2026-11-20",
      current: null,
      overdue_days: 2,
      dl_card: null,
    },
  ],
};

/** „Po terminie” bez faktur — przycisk listy na koniec miesiąca stoi i tak. */
const OVERDUE: OverdueInvoices = { invoices: [] };

export const SCREENS_FINANCE: Record<string, unknown> = {
  "/api/finance/settlements/overview": MONTH_CLOSE,
  "/api/finance/settlements/team": TEAM,
  "/api/finance/settlements/reminders": REMINDERS,
  "/api/finance/settlements/month-check": MONTH_CHECK,
  "/api/finance/settlements": SETTLEMENT_MONTH,
  "/api/finance/settlements/clients": SETTLEMENT_CLIENTS,
  // Karta „NIP-y z umów B2B” nad rozliczeniami: pusta, bez niej stoi błąd nad ekranem.
  "/api/finance/settlements/contract-nip-review": { items: [] },
  "/api/finance/settlements/time-reports/clients": { client_ids: [] },
  "/api/finance/settlements/einvoices/clients": { client_ids: [] },
  "/api/finance/settlements/client-acceptance": CLIENT_ACCEPTANCE,
  "/api/finance/settlements/client-documents": CLIENT_DOCUMENTS,
  "/api/finance/settlements/cases": CASES,
  [`/api/finance/settlements/rules/${CLIENT_ID}`]: CLIENT_RULES,
  ...Object.fromEntries(SETTLEMENT_MONTH.rows.map((row) => [`/api/finance/settlements/contract/${row.contract_id}`, DETAIL(row)])),
  "/api/finance/sales-invoices/overdue": OVERDUE,
};
