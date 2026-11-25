import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const del = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    delete: (...a: unknown[]) => del(...a),
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
      number: "NO123456789",
      kind: "foreign_id",
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
    expect(await row("NO123456789")).toHaveTextContent("ID zagraniczne NO123456789");
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
    const cell = within(await row("NO123456789"));
    expect(cell.getByText("klient ma już inny numer")).toBeInTheDocument();
    expect(cell.queryByRole("button", { name: "Przypisz" })).not.toBeInTheDocument();
    expect(cell.getByRole("button", { name: "Przypisz do…" })).toBeInTheDocument();
  });

  it("adds a group company number as an extra one after confirmation", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue({ data: { buyer_number: { retried: 2, matched: 1, extra: true } } });
    renderPanel();
    await user.click(within(await row("NO123456789")).getByRole("button", { name: "Jako dodatkowy" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Klient ma już inny numer");
    await user.click(within(dialog).getByRole("button", { name: "Dopisz jako dodatkowy" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/sales-invoices/unknown-buyers/assign", {
        number: "NO123456789",
        client_id: 36,
        extra: true,
      }),
    );
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(expect.stringContaining("Dodatkowy numer dopisany"), "success"),
    );
  });

  it("lists extra numbers and removes one after confirmation", async () => {
    const user = userEvent.setup();
    get.mockImplementation(async (url: string) => ({
      data: url.endsWith("/buyer-numbers")
        ? {
            numbers: [
              {
                id: 5,
                client_id: 36,
                client_name: "Klient Z Numerem",
                number: "FI01234567",
                kind: "vat_ue",
                source: "auto",
                created_at: "2026-11-25T10:00:00+00:00",
                invoices: 8,
              },
            ],
          }
        : RESPONSE,
    }));
    del.mockResolvedValue({ data: { removed: 5 } });
    renderPanel();
    expect(await screen.findByText("Dodatkowe numery klientów (1)")).toBeInTheDocument();
    expect(screen.getByText(/dopisany przez automat 25\.11\.2026 · 8 faktur/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Usuń" }));
    await user.click(await screen.findByRole("button", { name: "Usuń numer" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/api/finance/sales-invoices/buyer-numbers/5"));
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
