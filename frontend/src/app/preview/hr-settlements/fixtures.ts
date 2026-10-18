/**
 * Dane harnessu `/preview/hr-settlements` (rozliczenia zespołu, etap 4, makiety M1–M4, M7).
 *
 * Scena: rozliczenie POPRZEDNIEGO miesiąca względem dziś (makieta: październik
 * rozliczany na początku listopada). Osoby z obsady harnessów, NIP-y, numery
 * KSeF i kwoty ZMYŚLONE (NIP-y mają poprawną sumę kontrolną, bo formularz ją
 * sprawdza). Rachunków nie ma wcale — serwer wysyła tylko 4 ostatnie cyfry.
 */

import type {
  BillingDetails,
  MySettlementMonth,
  MySettlements,
  SettlementDetail,
  SettlementQueue,
  SettlementRow,
  SettlementStep,
} from "@/lib/api/hr-settlements";
import { monthYearPl, shiftMonth } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";

import { HR_CAST } from "../hr-fixtures";

const { ola, ewa, julia, tomasz, piotr } = HR_CAST;

export interface SettlementScene {
  today: string;
  /** Rok zakładki „Rozliczenie” (bieżący rok przeglądarki). */
  currentYear: number;
  /** Rozliczany miesiąc (poprzedni). */
  year: number;
  month: number;
  /** Miesiąc wcześniej (opłacony). */
  previousYear: number;
  previousMonth: number;
  /** Dzień w miesiącu po rozliczanym: `RRRR-MM-DD`. */
  after: (day: number) => string;
  /** Dzień w rozliczanym miesiącu: `RRRR-MM-DD`. */
  inMonth: (day: number) => string;
}

export function settlementScene(): SettlementScene {
  const today = warsawToday();
  const current = today.slice(0, 7);
  const closing = shiftMonth(current, -1);
  const previous = shiftMonth(current, -2);
  const [year, month] = closing.split("-").map(Number);
  const [previousYear, previousMonth] = previous.split("-").map(Number);
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    today,
    currentYear: Number(today.slice(0, 4)),
    year,
    month,
    previousYear,
    previousMonth,
    after: (day) => `${current}-${pad(day)}`,
    inMonth: (day) => `${closing}-${pad(day)}`,
  };
}

/** Zmyślony NIP z poprawną sumą kontrolną (9 cyfr + cyfra kontrolna). */
export function fictionalNip(prefix: string): string {
  const weights = [6, 5, 7, 2, 3, 4, 5, 6, 7];
  for (let tail = 0; tail < 100; tail += 1) {
    const body = (prefix + String(tail).padStart(2, "0")).slice(0, 9);
    const check = weights.reduce((sum, w, i) => sum + w * Number(body[i]), 0) % 11;
    if (check !== 10) return body + String(check);
  }
  throw new Error("brak NIP-u dla prefiksu");
}

const OLA_NIP = fictionalNip("1234563");
const EWA_NIP = fictionalNip("7777777");

function ksef(nip: string, day: string, tail: string): string {
  return `${nip}-${day.replace(/-/g, "")}-${tail}`;
}

function label(year: number, month: number): string {
  return monthYearPl({ year, month });
}

function steps(entries: [string, string, SettlementStep["state"], string | null, string | null][]): SettlementStep[] {
  return entries.map(([key, text, state, date, detail]) => ({ key, label: text, state, date, detail }));
}

/** M1: Ola na B2B — faktura zgodna, czeka na termin; poprzedni miesiąc opłacony. */
export function olaSettlements(scene: SettlementScene): MySettlements {
  const received = scene.after(4);
  const due = scene.after(18);
  const october: MySettlementMonth = {
    settlement_id: 5001,
    year: scene.year,
    month: scene.month,
    label: label(scene.year, scene.month),
    employment_type: "b2b",
    currency: "PLN",
    final: true,
    status: "approved",
    status_label: "Do zapłaty",
    amount: "17160.00",
    amount_basis: "net",
    hours: "168.00",
    hourly_rate: "95.00",
    hours_confirmed: true,
    items: [
      {
        kind: "hours",
        label: `Usługi, ${label(scene.year, scene.month)} · 160 h × 95,00`,
        amount: "15200.00",
        hours: "160.00",
        rate: "95.00",
        days: null,
        bonus_id: null,
      },
      {
        kind: "paid_days",
        label: "Płatne dni przerwy z umowy · 1 dzień (8 h × 95,00)",
        amount: "760.00",
        hours: "8.00",
        rate: "95.00",
        days: 1,
        bonus_id: null,
      },
      {
        kind: "bonus",
        label: "Premia · Rekruter · Placement: Data Engineer, Bank Przykładowy",
        amount: "1200.00",
        hours: null,
        rate: null,
        days: null,
        bonus_id: 4101,
      },
    ],
    steps: steps([
      ["hours", "Raport potwierdzony", "done", scene.after(3), "Marta Fikcyjna"],
      ["document", "Faktura w KSeF", "done", received, "FV 10/2026"],
      ["check", "Kwota zgodna", "done", null, "sprawdził NEXUS"],
      ["due", "Do zapłaty", "done", due, "14 dni od numeru KSeF"],
      ["paid", "Opłacono", "todo", null, "po przelewie"],
    ]),
    invoice: {
      id: 6001,
      source: "ksef",
      kind: "original",
      invoice_number: "FV 10/2026",
      ksef_number: ksef(OLA_NIP, received, "5F2A9C0D71B3-4E"),
      issue_date: received,
      sale_date: scene.inMonth(28),
      received_on: received,
      currency: "PLN",
      net_amount: "17160.00",
      vat_amount: "3946.80",
      gross_amount: "21106.80",
      net_total: "17160.00",
      gross_total: "21106.80",
      corrections: 0,
    },
    account_last4: "4521",
    account_source: "white_list",
    due_on: due,
    paid_on: null,
    correction_requested_at: null,
    discrepancy: "0.00",
    has_pdf: false,
  };
  const september: MySettlementMonth = {
    ...october,
    settlement_id: 4901,
    year: scene.previousYear,
    month: scene.previousMonth,
    label: label(scene.previousYear, scene.previousMonth),
    status: "paid",
    status_label: "Opłacono",
    amount: "16400.00",
    items: [
      { ...october.items[0], label: "Usługi · 164 h × 95,00", amount: "15600.00" },
      { ...october.items[2], amount: "800.00", bonus_id: 4001 },
    ],
    invoice: { ...october.invoice!, id: 5901, invoice_number: "FV 9/2026" },
    paid_on: scene.inMonth(15),
  };
  return {
    year: scene.currentYear,
    employment_type: "b2b",
    settlement_word: "Faktura",
    account_last4: "4521",
    account_source: "white_list",
    nip: OLA_NIP,
    months: [october, september],
  };
}

/** M2: Ewa na zleceniu (studentka) — przekazane do listy płac, PDF rozliczenia. */
export function ewaSettlements(scene: SettlementScene): MySettlements {
  const due = scene.after(10);
  const month: MySettlementMonth = {
    settlement_id: 5002,
    year: scene.year,
    month: scene.month,
    label: label(scene.year, scene.month),
    employment_type: "zlecenie",
    currency: "PLN",
    final: true,
    status: "approved",
    status_label: "Przekazano do listy płac",
    amount: "2944.00",
    amount_basis: "gross",
    hours: "92.00",
    hourly_rate: "32.00",
    hours_confirmed: true,
    items: [
      {
        kind: "hours",
        label: `Wynagrodzenie ze zlecenia, ${label(scene.year, scene.month)} · 92 h × 32,00`,
        amount: "2944.00",
        hours: "92.00",
        rate: "32.00",
        days: null,
        bonus_id: null,
      },
    ],
    steps: steps([
      ["hours", "Godziny potwierdzone", "done", scene.after(3), "Marta Fikcyjna"],
      ["amount", "Kwota policzona", "done", scene.after(4), null],
      ["approved", "Przekazane do listy płac", "done", scene.after(4), null],
      ["paid", "Wypłata", "todo", due, null],
    ]),
    invoice: null,
    account_last4: "0937",
    account_source: "manual",
    due_on: due,
    paid_on: null,
    correction_requested_at: null,
    discrepancy: null,
    has_pdf: true,
  };
  return {
    year: scene.currentYear,
    employment_type: "zlecenie",
    settlement_word: "Potwierdzenie godzin",
    account_last4: "0937",
    account_source: "manual",
    nip: null,
    months: [
      month,
      {
        ...month,
        settlement_id: 4902,
        year: scene.previousYear,
        month: scene.previousMonth,
        label: label(scene.previousYear, scene.previousMonth),
        status: "paid",
        status_label: "Wypłacono",
        amount: "2816.00",
        items: [{ ...month.items[0], label: "Wynagrodzenie ze zlecenia · 88 h × 32,00", amount: "2816.00" }],
        paid_on: scene.inMonth(8),
      },
    ],
  };
}

function row(overrides: Partial<SettlementRow> & Pick<SettlementRow, "id" | "user_id" | "name">): SettlementRow {
  return {
    employment_type: "b2b",
    form_short: "B2B",
    currency: "PLN",
    expected_amount: "0.00",
    amount_basis: "net",
    status: "awaiting_document",
    status_label: "Czeka na fakturę",
    due_on: null,
    document: { kind: "invoice", label: null, date: null },
    invoice_net: null,
    invoice_gross: null,
    discrepancy: null,
    problems: [],
    hours_confirmed: true,
    account_last4: null,
    account_source: null,
    correction_requested_at: null,
    override: null,
    approved_at: null,
    approved_by_name: null,
    paid_on: null,
    paid_source: null,
    paid_amount: null,
    mine: false,
    can_approve: false,
    can_mark_paid: true,
    has_pdf: false,
    ...overrides,
  };
}

/** M3: kolejka Płac — Piotr z uprawnieniem Płace. */
export function queue(scene: SettlementScene): SettlementQueue {
  const rows: SettlementRow[] = [
    row({
      id: 5003,
      user_id: ewa.id,
      name: "Ewa Makietowa",
      expected_amount: "14420.00",
      status: "mismatch",
      status_label: "Rozbieżność",
      due_on: scene.after(19),
      document: { kind: "invoice", label: "FV/27/10/26", date: scene.after(5), source: "ksef" },
      invoice_net: "14540.00",
      discrepancy: "120.00",
      problems: ["amount"],
      account_last4: "1180",
      account_source: "white_list",
    }),
    row({ id: 5004, user_id: julia.id, name: "Julia Próbna", expected_amount: "18900.00" }),
    row({ id: 5005, user_id: tomasz.id, name: "Tomasz Podglądowy", expected_amount: "12600.00" }),
    row({
      id: 5001,
      user_id: ola.id,
      name: "Ola Przykładowa",
      expected_amount: "17160.00",
      status: "ready",
      status_label: "Zgodna",
      due_on: scene.after(18),
      document: { kind: "invoice", label: "FV 10/2026", date: scene.after(4), source: "ksef" },
      invoice_net: "17160.00",
      discrepancy: "0.00",
      account_last4: "4521",
      account_source: "white_list",
      can_approve: true,
    }),
    row({
      id: 5006,
      user_id: 9201,
      name: "Celina Testowa",
      employment_type: "zlecenie",
      form_short: "Zlecenie",
      expected_amount: "2944.00",
      amount_basis: "gross",
      status: "approved",
      status_label: "Przekazano do listy płac",
      due_on: scene.after(10),
      document: { kind: "hours", label: "potwierdzenie godzin", date: null },
      has_pdf: true,
    }),
    row({
      id: 5007,
      user_id: piotr.id,
      name: piotr.name,
      employment_type: "uop",
      form_short: "UoP",
      expected_amount: "500.00",
      amount_basis: "gross",
      status: "ready",
      status_label: "Kwota policzona",
      due_on: scene.after(10),
      document: { kind: "payroll", label: "dane do listy płac", date: null },
      mine: true,
      can_mark_paid: false,
    }),
  ];
  return {
    year: scene.year,
    month: scene.month,
    label: label(scene.year, scene.month),
    period_status: "closed",
    rows,
    stats: {
      people: rows.length,
      to_pay: 1,
      ready: 2,
      mismatch: 1,
      awaiting_document: 2,
      hours_unconfirmed: 0,
      paid: 0,
    },
    missing: 0,
    cancelled: 0,
  };
}

/** M4: rozbieżność Ewy — faktura wyższa o 120,00 zł (godziny 153,3 zamiast 152). */
export function mismatchDetail(scene: SettlementScene): SettlementDetail {
  const base = queue(scene).rows[0];
  const received = scene.after(5);
  return {
    ...base,
    year: scene.year,
    month: scene.month,
    label: label(scene.year, scene.month),
    expected_items: [
      {
        kind: "hours",
        label: "Usługi · 152 h × 92,00",
        amount: "13984.00",
        hours: "152.00",
        rate: "92.00",
        days: null,
        bonus_id: null,
      },
      {
        kind: "bonus",
        label: "Premia · Rekruter · Placement: Tester, Klinika Testowa IT",
        amount: "436.00",
        hours: null,
        rate: null,
        days: null,
        bonus_id: 4102,
      },
    ],
    hours: "152.00",
    hourly_rate: "92.00",
    timesheet_approved_on: scene.after(3),
    invoices: [
      {
        id: 6003,
        source: "ksef",
        kind: "original",
        invoice_number: "FV/27/10/26",
        ksef_number: ksef(EWA_NIP, received, "0B91E4C2A7D8-1F"),
        issue_date: received,
        sale_date: scene.inMonth(28),
        received_on: received,
        currency: "PLN",
        net_amount: "14540.00",
        vat_amount: "3344.20",
        gross_amount: "17884.20",
        items: [
          { name: "Usługi rekrutacyjne", quantity: "153.3", unit: "h", unit_price: "92.00", net: "14104.00" },
          { name: "Premia", quantity: "1", unit: "szt.", unit_price: "436.00", net: "436.00" },
        ],
      },
    ],
    explain: [
      "Faktura netto wyższa o 120,00 PLN od kwoty z zamkniętego miesiąca.",
      "Godziny: 153,3 na fakturze, 152 w raporcie. Różnica 1,3 h × 92,00 = 119,60.",
    ],
    can_request_correction: true,
    can_request_override: true,
  };
}

/** M7: dane do rozliczeń Oli oglądane przez Kadry (z prawem zmiany). */
export function olaBilling(scene: SettlementScene): BillingDetails {
  return {
    user_id: ola.id,
    employment_type: "b2b",
    can_edit: true,
    nip: OLA_NIP,
    registry_name: "Ola Przykładowa Usługi Rekrutacyjne",
    vat_status: "active",
    vat_checked_at: `${scene.today}T09:00:00+02:00`,
    account_last4: "4521",
    account_source: "white_list",
    account_checked_at: `${scene.today}T09:00:00+02:00`,
    payment_terms_days: 14,
    symfonia_id: "000127",
    updated_at: `${scene.today}T09:00:00+02:00`,
    needs_second_person: false,
  };
}
