/**
 * Zakładka „Zużycie” przy zamówieniu kosztowym (ticket 21.10.2026, wersja B):
 * kafelki wspólnego budżetu, saldo zamówienia, podgląd i przekroczenie przed
 * zapisem, dwustopniowe usuwanie. Nazwiska i kwoty są zmyślone.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CostConsumptionTab } from "@/components/client-profile/orders/CostConsumptionTab";
import type { CostConsumptionsResponse, OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import {
  makeOrderGroup,
  makeOrderLine,
} from "@/components/client-profile/orders/__tests__/fixtures/order-groups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {
    listCostConsumptions: vi.fn(),
    putCostConsumption: vi.fn(),
    deleteCostConsumption: vi.fn(),
  },
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

const api = vi.mocked(orderGroupsApi);

function costGroup(): { group: OrderGroupRead; line: OrderLineRead } {
  const line = makeOrderLine({
    id: 844,
    consultant_name: "Jan Testowy",
    start_date: "2026-03-30",
    end_date: null,
    missing_consumption_month: "2026-09",
  });
  const group = makeOrderGroup({
    id: 102,
    order_number: "SAP 4500000001",
    is_cost_based: true,
    budget_amount: 37850,
    start_date: "2026-03-30",
    end_date: null,
    lines: [line],
  });
  return { group, line };
}

function response(overrides: Partial<CostConsumptionsResponse> = {}): CostConsumptionsResponse {
  return {
    order_number: "SAP 4500000001",
    budget_pool: 37850,
    budget_used: 0,
    budget_remaining: 37850,
    rows: [],
    people: [{ order_id: 844, name: "Jan Testowy", invoiced: 0 }],
    group_rows: [],
    ...overrides,
  };
}

function renderTab(canEdit = true) {
  const { group, line } = costGroup();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CostConsumptionTab clientId={15} group={group} line={line} canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

describe("CostConsumptionTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("przed wpisem: brak zejścia, budżet zamówienia i podgląd reszty po zapisie", async () => {
    const user = userEvent.setup();
    api.listCostConsumptions.mockResolvedValue({ data: response() } as never);
    renderTab();

    expect(await screen.findByText(/Brak zejścia za wrzesień 2026/)).toBeInTheDocument();
    expect(screen.getByText("Budżet zamówienia")).toBeInTheDocument();
    // Miesiąc z „Brak zejścia” jest wybrany od razu.
    expect(screen.getByLabelText("Miesiąc *")).toHaveValue("2026-09");

    await user.type(screen.getByLabelText("Kwota (zł) *"), "1540");

    expect(screen.getByText(/Po zapisie na zamówieniu zostanie 36\s?310,00/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dodaj wpis" })).toBeEnabled();
  });

  it("zapis wysyła kwotę, status i notatkę za wybrany miesiąc", async () => {
    const user = userEvent.setup();
    api.listCostConsumptions.mockResolvedValue({ data: response() } as never);
    api.putCostConsumption.mockResolvedValue({
      data: response({ budget_used: 1540, budget_remaining: 36310 }),
    } as never);
    renderTab();

    await user.type(await screen.findByLabelText("Kwota (zł) *"), "1540,00");
    await user.selectOptions(screen.getByLabelText("Status"), "accepted");
    await user.type(screen.getByLabelText("Notatka"), "  faktura 09  ");
    await user.click(screen.getByRole("button", { name: "Dodaj wpis" }));

    await waitFor(() =>
      expect(api.putCostConsumption).toHaveBeenCalledWith(15, 102, 844, "2026-09", {
        invoice_amount: 1540,
        status: "accepted",
        note: "faktura 09",
      }),
    );
  });

  it("przekroczenie: ostrzeżenie z kwotą, ale zapis dalej możliwy", async () => {
    const user = userEvent.setup();
    api.listCostConsumptions.mockResolvedValue({
      data: response({
        budget_used: 1540,
        budget_remaining: 36310,
        rows: [
          {
            period_month: "2026-09",
            invoice_amount: 1540,
            settled_amount: 1540,
            unsettled_amount: 0,
            source: "manual",
            balance_after: 36310,
          },
        ],
        people: [{ order_id: 844, name: "Jan Testowy", invoiced: 1540 }],
        group_rows: [{ order_id: 844, period_month: "2026-09", invoice_amount: 1540 }],
      }),
    } as never);
    renderTab();

    await user.selectOptions(await screen.findByLabelText("Miesiąc *"), "2026-10");
    await user.type(screen.getByLabelText("Kwota (zł) *"), "38000");

    expect(screen.getByText(/Przekroczenie budżetu o 1\s?690,00/)).toBeInTheDocument();
    expect(screen.getByText(/Jan Testowy za październik 2026/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz mimo przekroczenia" })).toBeEnabled();
  });

  it("wspólny budżet: kafelki całego zamówienia, udział osób i saldo zamówienia", async () => {
    api.listCostConsumptions.mockResolvedValue({
      data: response({
        budget_pool: 60000,
        budget_used: 42000,
        budget_remaining: 18000,
        rows: [
          {
            period_month: "2026-09",
            invoice_amount: 23500,
            settled_amount: 23500,
            unsettled_amount: 0,
            source: "import",
            balance_after: 18000,
          },
        ],
        people: [
          { order_id: 844, name: "Jan Testowy", invoiced: 23500 },
          { order_id: 845, name: "Ewa Przykładowa", invoiced: 18500 },
        ],
        group_rows: [
          { order_id: 844, period_month: "2026-09", invoice_amount: 23500 },
          { order_id: 845, period_month: "2026-09", invoice_amount: 18500 },
        ],
      }),
    } as never);
    renderTab();

    expect(await screen.findByText("Wspólny budżet zamówienia · 2 osoby")).toBeInTheDocument();
    expect(screen.getByText(/Ewa Przykładowa:/)).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Saldo zamówienia" })).toBeInTheDocument();
    // „Pozostało” = reszta całego zamówienia, nie 60 000 − kwoty tej osoby.
    expect(screen.getAllByText(/18\s?000,00/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/36\s?500,00/)).not.toBeInTheDocument();
  });

  it("usuwanie jest dwustopniowe, bez natywnego potwierdzenia", async () => {
    const user = userEvent.setup();
    api.listCostConsumptions.mockResolvedValue({
      data: response({
        rows: [
          {
            period_month: "2026-09",
            invoice_amount: 1540,
            settled_amount: 1540,
            unsettled_amount: 0,
            source: "manual",
            balance_after: 36310,
          },
        ],
        group_rows: [{ order_id: 844, period_month: "2026-09", invoice_amount: 1540 }],
      }),
    } as never);
    api.deleteCostConsumption.mockResolvedValue({ data: response() } as never);
    renderTab();

    await user.click(await screen.findByRole("button", { name: "Usuń wpis za wrz 2026" }));
    expect(api.deleteCostConsumption).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Potwierdź usunięcie" }));

    await waitFor(() => expect(api.deleteCostConsumption).toHaveBeenCalledWith(15, 102, 844, "2026-09"));
  });

  it("awaria odczytu nie wygląda jak brak wpisów", async () => {
    api.listCostConsumptions.mockRejectedValue(new Error("boom"));
    renderTab();

    expect(await screen.findByText(/Nie udało się wczytać rozliczeń/)).toBeInTheDocument();
    expect(screen.queryByText(/Brak wpisów/)).not.toBeInTheDocument();
  });

  it("bez uprawnień do edycji nie ma formularza ani akcji", async () => {
    api.listCostConsumptions.mockResolvedValue({ data: response() } as never);
    renderTab(false);

    expect(await screen.findByText(/Brak wpisów/)).toBeInTheDocument();
    expect(screen.queryByText("Nowy wpis miesięczny")).not.toBeInTheDocument();
  });
});
