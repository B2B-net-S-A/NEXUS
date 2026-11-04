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
import type { SalesKsefStatus } from "@/lib/api/client-invoicing";

import { CLIENT_MONTH } from "@/app/preview/client-invoicing/fixtures";

const STATUS: SalesKsefStatus = {
  mode: "test",
  enabled: true,
  disabled_reason: null,
  module_enabled: true,
  last_run_at: "2026-11-20T11:00:00+00:00",
  last_run_kind: "auto",
  last_success_at: "2026-11-20T11:00:00+00:00",
  last_error_text: null,
  last_error_at: null,
  blocked_until: null,
  last_counts: { saved: 3 },
  pending: 0,
  problems: [],
};

function mockApi() {
  get.mockImplementation((url: string) => {
    if (url === "/api/finance/sales-invoices/status") return Promise.resolve({ data: STATUS });
    if (url === "/api/finance/sales-invoices") {
      return Promise.resolve({
        data: {
          period: "2026-10",
          module_enabled: true,
          invoices: CLIENT_MONTH.invoices,
          summary: CLIENT_MONTH.summary,
        },
      });
    }
    if (url === "/api/finance/sales-invoices/credits") return Promise.resolve({ data: { credits: [] } });
    if (url === "/api/finance/sales-invoices/overdue") {
      return Promise.resolve({ data: { invoices: [CLIENT_MONTH.invoices[1]] } });
    }
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FinanceSalesInvoicesTab initialPeriod="2026-10" />
    </QueryClientProvider>,
  );
}

describe("FinanceSalesInvoicesTab", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    showToast.mockReset();
    mockApi();
  });

  it("offers decisions only where they apply", async () => {
    renderTab();
    const unmatched = await screen.findByTestId("sales-invoice-4");
    expect(within(unmatched).getByRole("button", { name: "Przypisz" })).toBeInTheDocument();
    expect(within(unmatched).getByRole("button", { name: "Pomiń" })).toBeInTheDocument();
    const difference = screen.getByTestId("sales-invoice-3");
    expect(within(difference).getByRole("button", { name: "Uznaj różnicę" })).toBeInTheDocument();
    const paid = screen.getByTestId("sales-invoice-1");
    expect(within(paid).queryByRole("button", { name: "Opłacono" })).not.toBeInTheDocument();
    expect(within(paid).queryByRole("button", { name: "Przypisz" })).not.toBeInTheDocument();
    expect(screen.getByText(/Ostatnie pobranie/)).toBeInTheDocument();
  });

  it("asks for a reason before skipping an invoice", async () => {
    post.mockResolvedValue({ data: { ...CLIENT_MONTH.invoices[3], match_status: "ignored" } });
    renderTab();
    const unmatched = await screen.findByTestId("sales-invoice-4");
    await userEvent.click(within(unmatched).getByRole("button", { name: "Pomiń" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Pomiń" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("co najmniej 3 znaki");
    expect(post).not.toHaveBeenCalled();
    await userEvent.type(within(dialog).getByLabelText("Powód"), "Sprzedaż sprzętu");
    await userEvent.click(within(dialog).getByRole("button", { name: "Pomiń" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/sales-invoices/4/ignore", {
        reason: "Sprzedaż sprzętu",
      }),
    );
  });
});
