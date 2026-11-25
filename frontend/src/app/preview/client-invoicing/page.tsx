"use client";

/**
 * Harness „Faktury do klientów” (etap 5, E8 cz. 1).
 *
 * Prawdziwe komponenty na zasianym cache, ZERO zapytań (`hr-harness.tsx`
 * odcina sieć). Klient „Bank Testowy S.A.”, październik 2026.
 *
 * Stany (`?state=`):
 * - `dl` (domyślnie) — zakładka „Faktury i rozliczenie” klienta oczami jego
 *   Delivery Leada: jedna strzałka miesiąca nad rozliczeniem z marżą, kroki
 *   miesiąca (RCP → do faktury → KSeF → zapłata), do faktury z zamówień
 *   obok faktur z KSeF, różnica, zaległość, brak faktury;
 * - `finance` — Finanse: faktury z KSeF z decyzjami (przypisz, pomiń, uznaj różnicę);
 * - `to-invoice` — Finanse: „Do faktury” wszystkich klientów z eksportem;
 * - `credits` — Finanse: wpłata z wyciągu do sprawdzenia;
 * - `overdue` — Finanse: po terminie z monitem 7/14/30 dni i VAT w PLN faktury w EUR.
 * Zapisy i pobrania blokuje harness.
 */

import { ClientInvoicesAndSettlementTab } from "@/components/clients/invoicing/ClientInvoicesAndSettlementTab";
import { FinanceSalesInvoicesTab } from "@/components/clients/invoicing/FinanceSalesInvoicesTab";
import { invoicingKeys } from "@/lib/api/client-invoicing";
import { settlementKeys } from "@/lib/api/client-settlements";

import { HR_CAST } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
  type HarnessUser,
} from "../hr-harness";
import {
  CLIENT_MONTH,
  CREDITS,
  DELIVERY_MONTH,
  KSEF_STATUS,
  OVERDUE,
  REMINDER,
  TO_INVOICE,
} from "./fixtures";

const CLIENT_ID = 7;
const PERIOD = "2026-10";
const STATE_KEYS = ["dl", "finance", "to-invoice", "credits", "overdue"] as const;
type State = (typeof STATE_KEYS)[number];

const STATES = [
  { key: "dl", label: "Klient: Faktury (DL)" },
  { key: "finance", label: "Finanse: faktury z KSeF" },
  { key: "to-invoice", label: "Finanse: do faktury" },
  { key: "credits", label: "Finanse: wpłaty" },
  { key: "overdue", label: "Finanse: po terminie" },
] as const;

const NOTES: Record<State, string> = {
  dl: "Dane fikcyjne, bez zapytań. Ogląda Delivery Lead klienta — kwoty własnego portfela, bez decyzji.",
  finance: "Dane fikcyjne, bez zapytań. Ogląda Finanse — decyzje przy fakturach do sprawdzenia.",
  "to-invoice": "Dane fikcyjne, bez zapytań. „Do faktury” wszystkich klientów za październik.",
  credits: "Dane fikcyjne, bez zapytań. Wpłata bez numeru faktury w tytule — kwota pasuje do jednej faktury.",
  overdue: "Dane fikcyjne, bez zapytań. Po terminie z dowodem z wyciągów: monit do klienta i VAT w PLN faktury w EUR.",
};

const DELIVERY_LEAD: HarnessUser = {
  id: 9101,
  name: "Kamil Przykładowy",
  email: "kamil.przykladowy@example.com",
  role: "delivery_lead",
};

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), STATE_KEYS, "dl");
  const client = harnessQueryClient();
  const [year, month] = PERIOD.split("-").map(Number);
  let user: HarnessUser = DELIVERY_LEAD;
  if (state === "dl") {
    client.setQueryData(invoicingKeys.client(CLIENT_ID, year, month), {
      ...CLIENT_MONTH,
      overdue: CLIENT_MONTH.invoices.filter((invoice) => invoice.overdue_days > 0),
    });
    // Sekcja „Rozliczenie miesiąca i marża” i krok „RCP” paska kroków czytają rozliczenia miesiąca.
    client.setQueryData(settlementKeys.delivery(CLIENT_ID, PERIOD), DELIVERY_MONTH);
  } else {
    user = { ...HR_CAST.piotr, role: "finance" };
    client.setQueryData(invoicingKeys.status, KSEF_STATUS);
    client.setQueryData(invoicingKeys.finance(year, month), {
      period: PERIOD,
      module_enabled: true,
      invoices: CLIENT_MONTH.invoices,
      summary: CLIENT_MONTH.summary,
    });
    client.setQueryData(invoicingKeys.toInvoice(year, month), TO_INVOICE);
    client.setQueryData(invoicingKeys.formChecks(year, month), {
      period: PERIOD,
      checked: CLIENT_MONTH.invoices.length,
      invoices: [],
    });
    client.setQueryData(invoicingKeys.credits, { credits: CREDITS });
    client.setQueryData(invoicingKeys.unknownBuyers, {
      buyers: [],
      summary: { invoices: 0, buyers: 0, with_suggestion: 0, totals: [] },
    });
    client.setQueryData(
      invoicingKeys.overdue,
      state === "overdue"
        ? OVERDUE
        : { invoices: CLIENT_MONTH.invoices.filter((invoice) => invoice.overdue_days > 0) },
    );
    client.setQueryData(invoicingKeys.reminder(CLIENT_ID, null), REMINDER);
  }
  return { user, client, value: { state } };
}

export default function ClientInvoicingPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Faktury do klientów"
      note={NOTES[state]}
      states={STATES}
      current={state}
    >
      {state === "dl" ? (
        <ClientInvoicesAndSettlementTab clientId={CLIENT_ID} initialPeriod={PERIOD} />
      ) : (
        <FinanceSalesInvoicesTab
          key={state}
          initialPeriod={PERIOD}
          initialView={state === "finance" ? "invoices" : state}
        />
      )}
    </HrHarnessShell>
  );
}
