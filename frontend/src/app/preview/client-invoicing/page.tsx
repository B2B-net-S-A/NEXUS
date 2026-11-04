"use client";

/**
 * Harness „Faktury do klientów” (etap 5, E8 cz. 1).
 *
 * Prawdziwe komponenty na zasianym cache, ZERO zapytań (`hr-harness.tsx`
 * odcina sieć). Klient „Bank Testowy S.A.”, październik 2026.
 *
 * Stany (`?state=`):
 * - `dl` (domyślnie) — zakładka „Faktury” klienta oczami jego Delivery Leada:
 *   do faktury z zamówień obok faktur z KSeF, różnica, zaległość, brak faktury;
 * - `finance` — Finanse: faktury z KSeF z decyzjami (przypisz, pomiń, uznaj różnicę);
 * - `to-invoice` — Finanse: „Do faktury” wszystkich klientów z eksportem;
 * - `credits` — Finanse: wpłata z wyciągu do sprawdzenia.
 * Zapisy i pobrania blokuje harness.
 */

import { ClientInvoicingTab } from "@/components/clients/invoicing/ClientInvoicingTab";
import { FinanceSalesInvoicesTab } from "@/components/clients/invoicing/FinanceSalesInvoicesTab";
import { invoicingKeys } from "@/lib/api/client-invoicing";

import { HR_CAST } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
  type HarnessUser,
} from "../hr-harness";
import { CLIENT_MONTH, CREDITS, KSEF_STATUS, TO_INVOICE } from "./fixtures";

const CLIENT_ID = 7;
const PERIOD = "2026-10";
const STATE_KEYS = ["dl", "finance", "to-invoice", "credits"] as const;
type State = (typeof STATE_KEYS)[number];

const STATES = [
  { key: "dl", label: "Klient: Faktury (DL)" },
  { key: "finance", label: "Finanse: faktury z KSeF" },
  { key: "to-invoice", label: "Finanse: do faktury" },
  { key: "credits", label: "Finanse: wpłaty" },
] as const;

const NOTES: Record<State, string> = {
  dl: "Dane fikcyjne, bez zapytań. Ogląda Delivery Lead klienta — kwoty własnego portfela, bez decyzji.",
  finance: "Dane fikcyjne, bez zapytań. Ogląda Finanse — decyzje przy fakturach do sprawdzenia.",
  "to-invoice": "Dane fikcyjne, bez zapytań. „Do faktury” wszystkich klientów za październik.",
  credits: "Dane fikcyjne, bez zapytań. Wpłata bez numeru faktury w tytule — kwota pasuje do jednej faktury.",
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
    client.setQueryData(invoicingKeys.credits, { credits: CREDITS });
    client.setQueryData(invoicingKeys.overdue, {
      invoices: CLIENT_MONTH.invoices.filter((invoice) => invoice.overdue_days > 0),
    });
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
        <ClientInvoicingTab clientId={CLIENT_ID} initialPeriod={PERIOD} />
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
