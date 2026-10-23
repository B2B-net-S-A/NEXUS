"use client";

/**
 * Harness Finanse → „Wydatki ze zgodą” (Zgody, etap 3 — 0486, makieta 5).
 *
 * Prawdziwa zakładka `ApprovedExpensesTab` na zasianym cache, ZERO zapytań
 * (`hr-harness.tsx`). Stany (`?state=`):
 * - `settle` (domyślnie) — „Do rozliczenia”: faktura w progu (Rozliczone),
 *   faktura +18% z dopłatą w drodze; „Czeka na fakturę”;
 * - `subscriptions` — rejestr: roczna za 9 dni, miesięczna z fakturą +18%;
 * - `invoices` — „Faktury bez zgody” z podpowiedzią zgody i stałymi kosztami.
 * Ogląda osoba z Finansów. Zapisy blokuje harness.
 */

import { ApprovedExpensesTab } from "@/components/finance/ApprovedExpensesTab";
import {
  expenseKeys,
  type ExpenseRequestRow,
  type ExpensesSummary,
  type SubscriptionRow,
} from "@/lib/api/approved-expenses";
import type { ApprovalDocument } from "@/lib/api/hr-approvals";
import { warsawToday } from "@/lib/warsaw-date";

import { HR_CAST } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";

const STATE_KEYS = ["settle", "subscriptions", "invoices"] as const;
type State = (typeof STATE_KEYS)[number];

const STATES = [
  { key: "settle", label: "Do rozliczenia", href: "?state=settle" },
  { key: "subscriptions", label: "Subskrypcje", href: "?state=subscriptions&expTab=subscriptions" },
  { key: "invoices", label: "Faktury bez zgody", href: "?state=invoices&expTab=invoices" },
] as const;

function iso(daysFromToday: number): string {
  const date = new Date();
  date.setDate(date.getDate() + daysFromToday);
  return date.toISOString().slice(0, 10);
}

function doc(partial: Partial<ApprovalDocument> & Pick<ApprovalDocument, "id">): ApprovalDocument {
  return {
    source: "ksef",
    doc_type: "invoice",
    status: "pinned",
    status_label: "do rozliczenia",
    approval_request_id: null,
    match_reason: "auto",
    match_reason_label: "przypięta sama (KSeF)",
    ksef_number: null,
    seller_nip: "1234563218",
    seller_name: "Dostawca Przykładowy sp. z o.o.",
    invoice_number: "FV 12/10/2026",
    issue_date: iso(-3),
    currency: "PLN",
    net_amount: null,
    vat_amount: null,
    gross_amount: "1150.00",
    file_name: null,
    has_file: false,
    read_status: null,
    topup: null,
    settled_at: null,
    settled_by_name: null,
    settle_note: null,
    close_note: null,
    comparison: null,
    can_edit: true,
    can_remove: true,
    can_request_topup: false,
    can_decide_topup: false,
    can_settle: true,
    ...partial,
  };
}

const FITS = (approved: string, documented: string) => ({
  status: "fits" as const,
  approved,
  documented,
  limit: String(Number(approved) * 1.1),
  excess: null,
  percent: null,
});

function summary(year: number, month: number): ExpensesSummary {
  return {
    year,
    month,
    approved_total: "21380.00",
    approved_count: 14,
    bonus_count: 4,
    by_kind: [
      { kind: "bonus", label: "Premia poza umową", amount: "7500.00" },
      { kind: "subscription", label: "Subskrypcja", amount: "4310.00" },
      { kind: "trip", label: "Delegacja", amount: "3900.00" },
      { kind: "training", label: "Szkolenie", amount: "3220.00" },
      { kind: "gift", label: "Prezent", amount: "1450.00" },
      { kind: "other", label: "Inny wydatek", amount: "1000.00" },
    ],
    other_currency_count: 1,
    awaiting_count: 2,
    awaiting_total: "1530.00",
    awaiting_oldest_days: 12,
    subscriptions_count: 2,
    subscriptions_monthly: "850.00",
    subscriptions_yearly: "10200.00",
    to_settle_count: 2,
    unmatched_count: 2,
  };
}

function request(partial: Partial<ExpenseRequestRow> & Pick<ExpenseRequestRow, "id" | "title">): ExpenseRequestRow {
  return {
    kind: "training",
    kind_label: "Szkolenie",
    requester_name: HR_CAST.ola.name,
    amount_text: "1 200 zł brutto",
    approved_amount: "1200.00",
    currency: "PLN",
    amount_basis: "gross",
    recurrence: "once",
    payer: "company_invoice",
    decided_at: iso(-10),
    expires_on: null,
    settlement_status: "documented",
    seller_nip: null,
    comparison: null,
    documents: [],
    ...partial,
  };
}

function toSettle() {
  return {
    to_settle: [
      request({
        id: 21,
        title: "Konferencja rekruterów IT — bilet",
        comparison: FITS("1200.00", "1150.00"),
        documents: [doc({ id: 31, approval_request_id: 21 })],
      }),
      request({
        id: 22,
        kind: "trip",
        kind_label: "Delegacja",
        title: "Gdańsk — warsztat u klienta",
        requester_name: HR_CAST.tomasz.name,
        amount_text: "900 zł brutto",
        approved_amount: "900.00",
        comparison: { status: "over", approved: "900.00", documented: "1062.00", limit: "990.00", excess: "162.00", percent: 18 },
        documents: [
          doc({
            id: 32,
            approval_request_id: 22,
            source: "upload",
            seller_name: "Hotel Przykładowy",
            invoice_number: "R/2026/10/77",
            gross_amount: "1062.00",
            has_file: true,
            file_name: "hotel.pdf",
            topup: { status: "pending", amount: "162.00", requested_at: iso(-1), decided_at: null, decided_by_name: null, note: null },
          }),
        ],
      }),
    ],
    awaiting: [
      request({ id: 23, kind: "gift", kind_label: "Prezent", title: "Kosz upominkowy dla klienta", requester_name: HR_CAST.adam.name, amount_text: "450 zł brutto", settlement_status: "open" }),
      request({ id: 24, kind: "other", kind_label: "Inny wydatek", title: "Monitor do pracy zdalnej", amount_text: "1 080 zł brutto", settlement_status: "open" }),
    ],
  };
}

function subscriptions(): SubscriptionRow[] {
  const base = {
    kind: "subscription" as const,
    kind_label: "Subskrypcja",
    currency: "PLN",
    status: "active" as const,
    ended_on: null,
    seller_nip: "1234563218",
  };
  return [
    {
      ...base,
      id: 41,
      title: "Narzędzie do ogłoszeń — 12 licencji",
      owner_user_id: HR_CAST.marta.id,
      owner_name: HR_CAST.marta.name,
      department: "Rekrutacja",
      recurrence: "yearly",
      amount_text: "7 200 zł brutto / rok",
      monthly: "600.00",
      renews_on: iso(9),
      renews_in_days: 9,
      renewal_asked: true,
      renewal_confirmed: false,
      last_document: doc({ id: 51, status: "settled", status_label: "rozliczona", issue_date: iso(-356), gross_amount: "7200.00", comparison: FITS("7200.00", "7200.00") }),
    },
    {
      ...base,
      id: 42,
      title: "Baza kontaktów — abonament",
      owner_user_id: HR_CAST.ewa.id,
      owner_name: HR_CAST.ewa.name,
      department: "Sprzedaż",
      recurrence: "monthly",
      amount_text: "250 zł brutto / mies.",
      monthly: "250.00",
      renews_on: null,
      renews_in_days: null,
      renewal_asked: false,
      renewal_confirmed: false,
      last_document: doc({
        id: 52,
        gross_amount: "295.00",
        comparison: { status: "over", approved: "250.00", documented: "295.00", limit: "275.00", excess: "45.00", percent: 18 },
      }),
    },
  ];
}

function invoices(): ApprovalDocument[] {
  return [
    {
      ...doc({
        id: 61,
        status: "unmatched",
        status_label: "bez zgody",
        match_reason: "no_approval",
        match_reason_label: "żadna zgoda nie ma tego sprzedawcy",
        seller_nip: "9876500011",
        seller_name: "Sklep Przykładowy",
        invoice_number: "FV 2026/10/1088",
        gross_amount: "1062.00",
        can_settle: false,
      }),
      suggestions: [
        { id: 24, title: "Monitor do pracy zdalnej", kind_label: "Inny wydatek", amount_text: "1 080 zł brutto", same_seller: false },
      ],
    },
    {
      ...doc({
        id: 62,
        status: "unmatched",
        status_label: "bez zgody",
        match_reason: "no_approval",
        match_reason_label: "żadna zgoda nie ma tego sprzedawcy",
        seller_nip: "9876500028",
        seller_name: "Biuro Rachunkowe Przykładowe",
        invoice_number: "12/10/2026",
        gross_amount: "2460.00",
        can_settle: false,
      }),
      suggestions: [],
    },
  ];
}

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), STATE_KEYS, "settle");
  const client = harnessQueryClient();
  const today = warsawToday();
  const year = Number(today.slice(0, 4));
  const month = Number(today.slice(5, 7));
  client.setQueryData(expenseKeys.summary(year, month), summary(year, month));
  client.setQueryData(expenseKeys.toSettle, toSettle());
  client.setQueryData(expenseKeys.subscriptions(false), subscriptions());
  client.setQueryData(expenseKeys.invoices("unmatched"), invoices());
  client.setQueryData(expenseKeys.fixedSellers, [
    { seller_nip: "9876500034", seller_name: "Operator Telefonii Przykładowy", note: "abonament", created_at: iso(-30) },
  ]);
  client.setQueryData(expenseKeys.requests(""), [
    { id: 24, title: "Monitor do pracy zdalnej", kind_label: "Inny wydatek", requester_name: HR_CAST.ola.name, amount_text: "1 080 zł brutto" },
  ]);
  return { user: HR_CAST.admin, client, value: { state } };
}

const NOTES: Record<State, string> = {
  settle: "Dane fikcyjne, bez zapytań. Ogląda osoba z Finansów.",
  subscriptions: "Dane fikcyjne, bez zapytań. Rejestr z zatwierdzonych zgód cyklicznych.",
  invoices: "Dane fikcyjne, bez zapytań. Faktury kosztowe z KSeF bez pasującej zgody.",
};

export default function FinanceApprovedExpensesPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state } = ready.value;
  return (
    <HrHarnessShell client={ready.client} title="Wydatki ze zgodą" note={NOTES[state]} states={STATES} current={state}>
      <div className="space-y-3.5">
        <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="font-display text-xl font-semibold leading-tight tracking-tight">Finanse</h1>
          <p className="text-[13px] text-muted-foreground">
            Zatwierdzone wydatki do rozliczenia, rejestr subskrypcji i faktury kosztowe bez zgody
          </p>
        </header>
        <ApprovedExpensesTab />
      </div>
    </HrHarnessShell>
  );
}
