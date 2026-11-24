import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const push = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

import { InvoiceRebateBox } from "@/components/clients/invoicing/issue/InvoiceRebateBox";
import { RebateCorrectionDialog } from "@/components/clients/invoicing/issue/RebateCorrectionDialog";
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
  corrections: [
    { month: 10, rate_diff: "0.5", excess: "200.00", amounts: [{ currency: "PLN", amount: "1.00" }], issued: [] },
  ],
  invoices: 3,
  excluded: 0,
  missing_fx: 0,
  archived: 0,
  unreadable: 0,
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
  issued: null,
};

function renderBox(clientId: number | null, rebate: InvoiceRebate = REBATE) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InvoiceRebateBox rebate={rebate} clientId={clientId} />
    </QueryClientProvider>,
  );
}

describe("szkic korekty rabatu za miesiąc przekroczenia", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    push.mockReset();
  });

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
    expect(within(dialog).getByText(/do KSeF idzie przyciskiem na karcie/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Pobierz XML (szkic)" })).toBeEnabled();
    expect(post).not.toHaveBeenCalled();
  });

  it("„Wystaw korektę” zapisuje szkic i otwiera jego kartę", async () => {
    get.mockResolvedValue({ data: DRAFT });
    post.mockResolvedValue({ data: { id: 501 } });
    const user = userEvent.setup();
    renderBox(11);
    await user.click(screen.getByRole("button", { name: "Szkic korekty rabatu za październik 2026" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(await within(dialog).findByRole("button", { name: "Wystaw korektę" }));
    expect(post).toHaveBeenCalledWith("/api/finance/issued-invoices/rebate-correction", {
      client_id: 11,
      year: 2026,
      month: 10,
      currency: "PLN",
    });
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/finance/faktury/501"));
  });

  it("bez XML-a nie da się wystawić; odmowa serwera widać w oknie", async () => {
    get.mockResolvedValue({ data: { ...DRAFT, xml_ready: false, xml_error: "Klient nie ma adresu." } });
    const user = userEvent.setup();
    renderBox(11);
    await user.click(screen.getByRole("button", { name: "Szkic korekty rabatu za październik 2026" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("button", { name: "Wystaw korektę" })).toBeDisabled();
    expect(within(dialog).getByText("Klient nie ma adresu.")).toBeInTheDocument();
  });

  it("pokazuje błąd serwera przy odmowie drugiej korekty", async () => {
    get.mockResolvedValue({ data: DRAFT });
    post.mockRejectedValue({
      isAxiosError: true,
      response: { status: 409, data: { detail: "Korekta rabatu za październik 2026 w PLN już jest." } },
    });
    const user = userEvent.setup();
    renderBox(11);
    await user.click(screen.getByRole("button", { name: "Szkic korekty rabatu za październik 2026" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(await within(dialog).findByRole("button", { name: "Wystaw korektę" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/już jest/);
    expect(push).not.toHaveBeenCalled();
  });

  it("wystawiona korekta: odnośnik na karcie i w oknie zamiast drugiego wystawienia", async () => {
    const issued = {
      id: 501,
      currency: "PLN",
      status: "draft" as const,
      status_label: "Szkic",
      invoice_number: null,
    };
    renderBox(11, { ...REBATE, corrections: [{ ...REBATE.corrections[0], issued: [issued] }] });
    expect(screen.getByRole("link", { name: "Korekta — szkic bez numeru" })).toHaveAttribute(
      "href",
      "/finance/faktury/501",
    );
    expect(screen.queryByRole("button", { name: /Szkic korekty rabatu/ })).toBeNull();
  });

  it("okno podglądu z wystawioną korektą prowadzi do niej", async () => {
    const issued = { id: 501, currency: "PLN", status: "sent" as const, status_label: "W KSeF", invoice_number: "KOR/1/11/2026" };
    get.mockResolvedValue({ data: { ...DRAFT, issued } });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RebateCorrectionDialog query={{ clientId: 11, year: 2026, month: 10, currency: "PLN" }} onClose={() => {}} />
      </QueryClientProvider>,
    );
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("link", { name: "Otwórz korektę" })).toHaveAttribute(
      "href",
      "/finance/faktury/501",
    );
    expect(within(dialog).queryByRole("button", { name: "Wystaw korektę" })).toBeNull();
    expect(within(dialog).getByText(/KOR\/1\/11\/2026/)).toBeInTheDocument();
  });

});
