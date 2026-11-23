import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));

const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

import { FinanceSalesInvoicesTab } from "@/components/clients/invoicing/FinanceSalesInvoicesTab";
import {
  paymentNote,
  reminderClients,
  vatUnpaidText,
} from "@/components/clients/invoicing/invoicing-format";
import type { ReminderDraft, SalesInvoice } from "@/lib/api/client-invoicing";

import { CLIENT_MONTH } from "@/app/preview/client-invoicing/fixtures";

const LATE: SalesInvoice = {
  ...CLIENT_MONTH.invoices[1],
  overdue_days: 16,
  escalation: "second",
  statements_until: "2026-11-19",
};
const VAT_LATE: SalesInvoice = {
  ...CLIENT_MONTH.invoices[1],
  id: 9,
  invoice_number: "FS 10/9/2026/UE",
  client_id: 8,
  client_name: "Klient Zagraniczny",
  currency: "EUR",
  gross: "1230.00",
  paid: "1000.00",
  to_pay: "230.00",
  payment_status: "partial",
  overdue_days: 8,
  escalation: "first",
  statements_until: "2026-11-19",
  vat_pln_unpaid: {
    vat: "230.00",
    currency: "EUR",
    vat_pln: "977.50",
    rate: "4.25",
    rate_date: "2026-10-30",
    rate_source: "nbp",
  },
};

const DRAFT: ReminderDraft = {
  client_id: 7,
  client_name: "Bank Testowy",
  level: "second",
  level_label: "Ponowne wezwanie do zapłaty",
  first_day: 7,
  language: "pl",
  subject: "Ponowne wezwanie do zapłaty — 1 faktura po terminie",
  text: "Dzień dobry,\n\nponownie prosimy o zapłatę…",
  invoices: [
    {
      invoice_id: 2,
      invoice_number: LATE.invoice_number,
      ksef_number: LATE.ksef_number,
      due_date: LATE.due_date,
      currency: "PLN",
      to_pay: LATE.to_pay,
      overdue_days: 16,
      escalation: "second",
      vat: null,
      vat_pln: null,
    },
  ],
  totals: [{ currency: "PLN", amount: LATE.to_pay }],
  recipients: [
    { email: "ap@example.com", name: "Dział płatności", source: "contact", source_label: "kontakt klienta (finanse)" },
    { email: "paczka@example.com", name: null, source: "send_to", source_label: "adres paczki do klienta (reguły rozliczeń)" },
  ],
  last_sent_at: null,
  last_level: null,
};

function mockApi(draft: ReminderDraft = DRAFT) {
  get.mockImplementation((url: string) => {
    if (url === "/api/finance/sales-invoices/status") {
      return Promise.resolve({ data: { mode: "off", enabled: false, module_enabled: true, last_counts: {}, problems: [] } });
    }
    if (url === "/api/finance/sales-invoices") {
      return Promise.resolve({
        data: { period: "2026-10", module_enabled: true, invoices: [], summary: CLIENT_MONTH.summary },
      });
    }
    if (url === "/api/finance/sales-invoices/credits") return Promise.resolve({ data: { credits: [] } });
    if (url === "/api/finance/sales-invoices/unknown-buyers") {
      return Promise.resolve({ data: { buyers: [], summary: { buyers: 0, invoices: 0, totals: [] } } });
    }
    if (url === "/api/finance/sales-invoices/overdue") {
      return Promise.resolve({
        data: {
          invoices: [LATE, VAT_LATE],
          payment_unknown: 0,
          vat_pln_unpaid: { count: 1, total_pln: "977.50", without_rate: 0 },
        },
      });
    }
    if (url === "/api/finance/sales-invoices/overdue/reminder") return Promise.resolve({ data: draft });
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FinanceSalesInvoicesTab initialPeriod="2026-11" initialView="overdue" />
    </QueryClientProvider>,
  );
}

describe("Po terminie: monit i VAT w PLN", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    showToast.mockReset();
    mockApi();
  });

  it("lists clients to remind with the escalation level and the unpaid VAT sentence", async () => {
    renderTab();
    const list = await screen.findByTestId("reminder-clients");
    const items = within(list).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent(LATE.client_name ?? "");
    expect(items[0]).toHaveTextContent("ponowne wezwanie");
    expect(items[1]).toHaveTextContent("Klient Zagraniczny");
    expect(items[1]).toHaveTextContent("przypomnienie");
    expect(screen.getByTestId("overdue-vat-pln")).toHaveTextContent(
      "1 faktura walutowa ma zapłacone netto w walucie, a VAT w PLN nie wpłynął",
    );
    // VAT faktury walutowej w kolumnie zapłaty.
    expect(screen.getByTestId("sales-invoice-9")).toHaveTextContent("VAT do zapłaty 977,50");
  });

  it("sends the reminder only after the click and the confirmation", async () => {
    post.mockResolvedValue({ data: { sent: 1, failed: 0, level: "second" } });
    renderTab();
    const list = await screen.findByTestId("reminder-clients");
    await userEvent.click(within(list).getAllByRole("button", { name: "Przygotuj monit" })[0]);

    const form = await screen.findByTestId("payment-reminder-form");
    expect(get).toHaveBeenCalledWith("/api/finance/sales-invoices/overdue/reminder", {
      params: { client_id: 7 },
    });
    expect(within(form).getByLabelText("Temat")).toHaveValue(DRAFT.subject);
    // Domyślnie pierwszy kontakt; drugi adres można dołożyć.
    expect(within(form).getByLabelText("ap@example.com")).toBeChecked();
    expect(within(form).getByLabelText("paczka@example.com")).not.toBeChecked();
    await userEvent.type(within(form).getByLabelText("Treść"), " Dopisek.");
    expect(post).not.toHaveBeenCalled();

    await userEvent.click(within(form).getByRole("button", { name: "Wyślij monit" }));
    expect(post).not.toHaveBeenCalled();
    const confirm = await screen.findByRole("dialog", { name: "Wysłać monit do klienta?" });
    expect(confirm).toHaveTextContent("ap@example.com");
    await userEvent.click(within(confirm).getByRole("button", { name: "Wyślij monit" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/sales-invoices/overdue/reminder", {
        client_id: 7,
        to: ["ap@example.com"],
        subject: DRAFT.subject,
        text: `${DRAFT.text} Dopisek.`,
      }),
    );
    expect(showToast).toHaveBeenCalledWith("Monit wysłany", "success");
  });

  it("does not send when the mail channel did not confirm", async () => {
    post.mockResolvedValue({ data: { sent: 0, failed: 1, level: "second" } });
    renderTab();
    const list = await screen.findByTestId("reminder-clients");
    await userEvent.click(within(list).getAllByRole("button", { name: "Przygotuj monit" })[0]);
    const form = await screen.findByTestId("payment-reminder-form");
    await userEvent.click(within(form).getByRole("button", { name: "Wyślij monit" }));
    await userEvent.click(within(await screen.findByRole("dialog", { name: "Wysłać monit do klienta?" })).getByRole("button", { name: "Wyślij monit" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("monit nie wyszedł");
    expect(showToast).not.toHaveBeenCalled();
  });

  it("without a billing contact the reminder cannot be sent", async () => {
    get.mockReset();
    mockApi({ ...DRAFT, recipients: [] });
    renderTab();
    const list = await screen.findByTestId("reminder-clients");
    await userEvent.click(within(list).getAllByRole("button", { name: "Przygotuj monit" })[0]);
    const form = await screen.findByTestId("payment-reminder-form");
    expect(form).toHaveTextContent("Klient nie ma kontaktu rozliczeniowego");
    expect(within(form).getByRole("button", { name: "Wyślij monit" })).toBeDisabled();
  });

  it("before the 7th day the draft is there but sending is off", async () => {
    get.mockReset();
    mockApi({ ...DRAFT, level: null, level_label: null });
    renderTab();
    const list = await screen.findByTestId("reminder-clients");
    await userEvent.click(within(list).getAllByRole("button", { name: "Przygotuj monit" })[0]);
    const form = await screen.findByTestId("payment-reminder-form");
    expect(form).toHaveTextContent("Monit od 7. dnia po terminie");
    expect(within(form).getByRole("button", { name: "Wyślij monit" })).toBeDisabled();
  });
});

describe("invoicing-format: monity", () => {
  it("groups overdue invoices per client with the highest level", () => {
    const clients = reminderClients([
      { ...LATE, overdue_days: 8, escalation: "first" },
      { ...LATE, id: 3, overdue_days: 31, escalation: "final" },
      VAT_LATE,
      { ...LATE, id: 4, client_id: null },
    ]);
    expect(clients.map((c) => [c.clientId, c.invoices, c.maxDays, c.level])).toEqual([
      [7, 2, 31, "final"],
      [8, 1, 8, "first"],
    ]);
  });

  it("says when the PLN amount is missing a rate", () => {
    expect(vatUnpaidText({ count: 2, total_pln: null, without_rate: 2 })).toContain(
      "bez kursu NBP: 2 — kwotę w PLN weź z faktury",
    );
  });

  it("shows VAT in the payment note instead of the EUR remainder", () => {
    expect(paymentNote(VAT_LATE)).toBe("netto zapłacone · VAT do zapłaty 977,50 zł · wyciągi do 19.11");
    expect(
      paymentNote({ ...VAT_LATE, vat_pln_unpaid: { ...VAT_LATE.vat_pln_unpaid!, vat_pln: null } }),
    ).toContain("VAT do zapłaty 230,00");
  });
});
