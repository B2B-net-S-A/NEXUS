import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: vi.fn(),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { ClientInvoicesAndSettlementTab } from "@/components/clients/invoicing/ClientInvoicesAndSettlementTab";

import { CLIENT_MONTH, DELIVERY_MONTH } from "@/app/preview/client-invoicing/fixtures";
import type { DeliverySettlements } from "@/lib/api/client-settlements";
import { warsawToday } from "@/lib/warsaw-date";

/** Wrzesień ma w rozliczeniach inną osobę niż październik — po niej widać, który miesiąc stoi w sekcji. */
const SEPTEMBER: DeliverySettlements = {
  ...DELIVERY_MONTH,
  month: "2026-09",
  rows: [{ ...DELIVERY_MONTH.rows[0], contract_id: 9, person: "Piotr Wrześniowy", order_number: "ZAM/2026/090" }],
};

function answer() {
  get.mockImplementation((url: string, config?: { params?: Record<string, unknown> }) => {
    const params = config?.params ?? {};
    if (url === "/api/my-clients/7/settlements") {
      return Promise.resolve({ data: params.month === "2026-09" ? SEPTEMBER : { ...DELIVERY_MONTH, month: params.month } });
    }
    if (url === "/api/clients/7/invoicing") {
      return Promise.resolve({
        data: { ...CLIENT_MONTH, period: `${params.year}-${String(params.month).padStart(2, "0")}` },
      });
    }
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

function renderTab(initialPeriod: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientInvoicesAndSettlementTab clientId={7} initialPeriod={initialPeriod} />
    </QueryClientProvider>,
  );
}

function settlement() {
  return screen.getByRole("region", { name: "Rozliczenie miesiąca i marża" });
}

describe("ClientInvoicesAndSettlementTab", () => {
  beforeEach(() => {
    get.mockReset();
    answer();
  });

  it("moves the margin section and the invoice table together with one month arrow", async () => {
    renderTab("2026-10");
    await screen.findByTestId("billing-row-g11");
    await waitFor(() => expect(within(settlement()).getByText("Ewa Przykładowa")).toBeInTheDocument());
    expect(get).toHaveBeenCalledWith("/api/my-clients/7/settlements", { params: { month: "2026-10" } });
    expect(get).toHaveBeenCalledWith("/api/clients/7/invoicing", { params: { year: 2026, month: 10 } });

    // Jedna strzałka na całą zakładkę: sekcja marży nie ma już własnej.
    expect(screen.getAllByRole("button", { name: "Poprzedni miesiąc" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Następny miesiąc" })).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "Poprzedni miesiąc" }));

    expect(screen.getByRole("heading", { name: "Wrzesień 2026" })).toBeInTheDocument();
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/api/clients/7/invoicing", { params: { year: 2026, month: 9 } }),
    );
    expect(get).toHaveBeenCalledWith("/api/my-clients/7/settlements", { params: { month: "2026-09" } });
    // Sekcja marży pokazuje wrzesień, a nie dalej październik (zrzut ze stagingu, klient 39, 20.11.2026).
    await waitFor(() => expect(within(settlement()).getByText("Piotr Wrześniowy")).toBeInTheDocument());
    expect(within(settlement()).queryByText("Ewa Przykładowa")).not.toBeInTheDocument();
  });

  it("stops the arrow at the current month", async () => {
    const current = warsawToday().slice(0, 7);
    renderTab(current);
    await screen.findByTestId("billing-row-g11");
    const next = screen.getByRole("button", { name: "Następny miesiąc" });
    expect(next).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Poprzedni miesiąc" }));
    expect(next).toBeEnabled();
  });
});
