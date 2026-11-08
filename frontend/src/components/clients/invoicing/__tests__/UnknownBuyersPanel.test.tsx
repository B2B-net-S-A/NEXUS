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
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast }) }));

import { UnknownBuyersPanel } from "@/components/clients/invoicing/UnknownBuyersPanel";
import type { UnknownBuyersResponse } from "@/lib/api/client-invoicing";

const RESPONSE: UnknownBuyersResponse = {
  buyers: [
    {
      number: "3333333333",
      kind: "nip",
      buyer_name: "Nabywca Testowy S.A.",
      invoices: 13,
      totals: [{ currency: "PLN", amount: "301269.00" }],
      first_date: "2026-08-07",
      last_date: "2026-10-13",
      assignable: true,
      suggestion: { client_id: 35, client_name: "Klient Testowy", state: "add" },
    },
    {
      number: "4444444444",
      kind: "nip",
      buyer_name: "Inny Nabywca",
      invoices: 2,
      totals: [{ currency: "EUR", amount: "10.00" }],
      first_date: "2026-09-01",
      last_date: "2026-09-01",
      assignable: true,
      suggestion: { client_id: 36, client_name: "Klient Z Numerem", state: "differs" },
    },
    {
      number: null,
      kind: null,
      buyer_name: null,
      invoices: 1,
      totals: [{ currency: "PLN", amount: "5.00" }],
      first_date: "2026-09-01",
      last_date: "2026-09-01",
      assignable: false,
      suggestion: null,
    },
  ],
  summary: {
    invoices: 16,
    buyers: 2,
    with_suggestion: 2,
    totals: [{ currency: "PLN", amount: "301274.00" }],
  },
};

function renderPanel() {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queries}>
      <UnknownBuyersPanel />
    </QueryClientProvider>,
  );
}

const row = (number: string) => screen.findByTestId(`unknown-buyer-${number}`);

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue({ data: RESPONSE });
  post.mockResolvedValue({ data: { buyer_number: { retried: 13, matched: 9 } } });
});

describe("UnknownBuyersPanel", () => {
  it("summarises the queue and groups by number", async () => {
    renderPanel();
    expect(await screen.findByText(/16 faktur · 2 nabywców · 2 z podpowiedzią/)).toBeInTheDocument();
    expect(await row("3333333333")).toHaveTextContent("Klient Testowy");
    expect(await row("3333333333")).toHaveTextContent("NIP 3333333333");
    expect(screen.getByTestId("unknown-buyer-none")).toHaveTextContent("bez numeru");
  });

  it("assigns the suggestion after confirmation", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(within(await row("3333333333")).getByRole("button", { name: "Przypisz" }));
    await user.click(await screen.findByRole("button", { name: "Przypisz" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/finance/sales-invoices/unknown-buyers/assign",
        { number: "3333333333", client_id: 35 },
      ),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.stringContaining("13"), "success"));
  });

  it("offers no one-click assign for a client that already has a number", async () => {
    renderPanel();
    const cell = within(await row("4444444444"));
    expect(cell.getByText("klient ma już inny numer")).toBeInTheDocument();
    expect(cell.queryByRole("button", { name: "Przypisz" })).not.toBeInTheDocument();
    expect(cell.getByRole("button", { name: "Przypisz do…" })).toBeInTheDocument();
  });

  it("requires a reason to skip and sends it", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue({ data: { skipped: 13 } });
    renderPanel();
    await user.click(within(await row("3333333333")).getByRole("button", { name: "Pomiń" }));
    const dialogButton = await screen.findByRole("button", { name: "Pomiń", hidden: false });
    await user.click(dialogButton);
    expect(await screen.findByRole("alert")).toHaveTextContent("co najmniej 3 znaki");
    expect(post).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Powód"), "Sprzedaż sprzętu");
    await user.click(dialogButton);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/sales-invoices/unknown-buyers/skip", {
        number: "3333333333",
        reason: "Sprzedaż sprzętu",
      }),
    );
  });

  it("does not offer actions for an invoice without a buyer number", async () => {
    renderPanel();
    const cell = within(await row("none"));
    expect(cell.queryByRole("button")).not.toBeInTheDocument();
  });

  it("failure does not look like an empty queue", async () => {
    get.mockRejectedValue(new Error("boom"));
    renderPanel();
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.queryByText(/są przypisani do klientów/)).not.toBeInTheDocument();
  });

  it("hides the queue total when the server withholds it", async () => {
    get.mockResolvedValue({
      data: { ...RESPONSE, summary: { ...RESPONSE.summary, totals: [], totals_hidden: true } },
    });
    renderPanel();
    expect(await screen.findByText(/z podpowiedzią/)).not.toHaveTextContent("netto");
  });
});
