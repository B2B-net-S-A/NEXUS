import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...a: unknown[]) => get(...a) },
}));

import { FormChecksPanel } from "@/components/clients/invoicing/FormChecksPanel";
import type { FormChecksReport } from "@/lib/api/client-invoicing";

const REPORT: FormChecksReport = {
  period: "2026-10",
  checked: 12,
  invoices: [
    {
      invoice_id: 1,
      invoice_number: "7/10/2026",
      ksef_number: "1111111111-20261031-AAAAAAAAAAAA-01",
      client_id: 3,
      client_name: "Bank Testowy S.A.",
      issue_date: "2026-10-31",
      sale_date: "2026-10-31",
      problems: ["Pozycja 1: w polu ID jest „Jan Przykładowy” zamiast kodu osoby (litera i 5–7 cyfr)."],
    },
  ],
};

function wrap() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FormChecksPanel year={2026} month={10} period="2026-10" />
    </QueryClientProvider>,
  );
}

describe("FormChecksPanel", () => {
  beforeEach(() => {
    get.mockReset();
  });

  it("shows the count and expands to the remarks", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: REPORT });
    wrap();
    const toggle = await screen.findByRole("button", { name: /1 faktura z uwagami \(z 12\)/ });
    expect(screen.queryByText(/w polu ID jest/)).not.toBeInTheDocument();
    await user.click(toggle);
    expect(screen.getByText(/w polu ID jest/)).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/finance/sales-invoices/form-checks", {
      params: { year: 2026, month: 10 },
    });
  });

  it("says no remarks only after a successful check", async () => {
    get.mockResolvedValue({ data: { ...REPORT, invoices: [] } });
    wrap();
    expect(await screen.findByText(/bez uwag \(12 faktur za październik 2026\)/)).toBeInTheDocument();
  });

  it("does not pretend an outage means no remarks", async () => {
    get.mockRejectedValue(new Error("awaria"));
    wrap();
    expect(await screen.findByText("Spróbuj ponownie")).toBeInTheDocument();
    expect(screen.queryByText(/bez uwag/)).not.toBeInTheDocument();
  });
});
