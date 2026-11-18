import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...a: unknown[]) => get(...a), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

import { InvoiceRebateBox } from "@/components/clients/invoicing/issue/InvoiceRebateBox";
import type { InvoiceRebate, RebateCorrectionDraft } from "@/lib/api/issued-invoices";

// Dane fikcyjne.
const REBATE: InvoiceRebate = {
  year: 2026,
  month: 11,
  threshold_currency: "PLN",
  tiers: [
    { up_to: "1000.00", rate: "2.5" },
    { up_to: null, rate: "3" },
  ],
  turnover: "1500.00",
  turnover_before: "1200.00",
  rate: "3",
  next_rate: null,
  to_next: null,
  due: "40.00",
  on_invoice: "9.00",
  currency: "PLN",
  corrections: [{ month: 10, rate_diff: "0.5", excess: "200.00", amounts: [{ currency: "PLN", amount: "1.00" }] }],
  invoices: 3,
  excluded: 0,
  missing_fx: 0,
};

const DRAFT: RebateCorrectionDraft = {
  client_id: 11,
  client_name: "Bank Testowy S.A.",
  year: 2026,
  month: 10,
  currency: "PLN",
  threshold_currency: "PLN",
  rate_diff: "0.5",
  excess: "200.00",
  amount: "1.00",
  lines: [{ name: "Opust", vat_rate: "23", vat_label: "23%", net: "-1.00" }],
  net: "-1.00",
  vat: "-0.23",
  gross: "-1.23",
  invoices: [
    { number: "20/10/2026", issue_date: "2026-10-31", ksef_number: "9876543210-20261031-E40000000001-1A", base: "300.00" },
  ],
  invoice_count: 1,
  other_amounts: [],
  fx_rate: null,
  fx_date: null,
  xml_ready: true,
  xml_error: null,
  correction_type: "2",
};

function renderBox(clientId: number | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InvoiceRebateBox rebate={REBATE} clientId={clientId} />
    </QueryClientProvider>,
  );
}

describe("szkic korekty rabatu za miesiąc przekroczenia", () => {
  beforeEach(() => get.mockReset());

  it("bez klienta nie ma przycisku szkicu", () => {
    renderBox(null);
    expect(screen.queryByRole("button", { name: /Szkic korekty rabatu/ })).toBeNull();
  });

  it("pokazuje kwotę, stawki VAT i faktury korygowane; nic nie wysyła", async () => {
    get.mockResolvedValue({ data: DRAFT });
    const user = userEvent.setup();
    renderBox(11);
    await user.click(screen.getByRole("button", { name: "Szkic korekty rabatu za październik 2026" }));
    expect(get).toHaveBeenCalledWith(
      "/api/finance/issued-invoices/rebate-correction?client_id=11&year=2026&month=10&currency=PLN",
    );
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Faktury korygowane: 1")).toBeInTheDocument();
    expect(within(dialog).getByText("20/10/2026")).toBeInTheDocument();
    expect(within(dialog).getByText("Netto, VAT 23%")).toBeInTheDocument();
    expect(within(dialog).getByText("Korekta brutto").nextSibling).toHaveTextContent(/-1,23\szł/);
    expect(within(dialog).getByText(/nie wysyła do KSeF/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Pobierz XML (szkic)" })).toBeEnabled();
  });

});
