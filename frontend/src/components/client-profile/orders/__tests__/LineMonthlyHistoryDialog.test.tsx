import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CONSUMPTION_STATUS_LABEL,
  LineMonthlyHistoryDialog,
} from "@/components/client-profile/orders/LineMonthlyHistoryDialog";
import type {
  LineConsumptionRow,
  OrderGroupRead,
  OrderLineRead,
} from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {
    listConsumptions: vi.fn(),
    putConsumption: vi.fn(),
    deleteConsumption: vi.fn(),
  },
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

const LINE: OrderLineRead = {
  id: 44,
  group_id: 910,
  contract_id: 100,
  candidate_id: 5,
  consultant_name: "Anna Przykładowa",
  job_id: null,
  job_title: null,
  status: "active",
  is_active: true,
  start_date: "2025-10-01",
  end_date: null,
  rate_cost: null,
  rate_revenue: null,
  input_value: 190,
  input_mode: "md",
  md_total: 190,
  md_remaining: 36,
  md_manual_adjustment: 0,
  predecessor_order_id: null,
  predecessor_consultant_name: null,
  invoiced_total: null,
  unsettled_total: null,
  missing_consumption_month: null,
  md_used: 154,
  md_optional_total: 170,
  md_base_used: 154,
  md_optional_used: 0,
  replaced_by_order_id: null,
  replaced_by_consultant_name: null,
};

const GROUP: OrderGroupRead = {
  id: 910,
  client_id: 115,
  order_number: "CeZ/242/2025/Z-7",
  start_date: "2025-10-01",
  end_date: null,
  notes: null,
  created_at: "2025-10-01T10:00:00Z",
  status: "active",
  status_label: "Aktywne",
  closure_date: null,
  closure_reason: null,
  is_cost_based: false,
  is_md_budget_based: false,
  budget_amount: null,
  budget_used: null,
  budget_remaining: null,
  budget_manual_adjustment: null,
  md_budget_total: null,
  md_budget_used: null,
  md_budget_remaining: null,
  md_budget_manual_adjustment: null,
  predecessor_group_id: null,
  filename: null,
  has_file: false,
  content_type: null,
  size_bytes: null,
  file_uploaded_at: null,
  can_add_consultant: true,
  executive_contract: null,
  md_positions_total: null,
  md_used_total: null,
  contract_value_pln: null,
  used_value_pln: null,
  lines: [LINE],
  active_consultants: 1,
  event_count: 0,
  future_orders: [],
};

const ROWS: LineConsumptionRow[] = [
  {
    period_month: "2025-12",
    md_reported: 20,
    status: "accepted",
    note: null,
    source: "import",
    import_id: 501,
    created_by_name: "Import z Finansów",
    updated_at: "2026-01-05T08:00:00Z",
  },
  {
    period_month: "2026-02",
    md_reported: 18.5,
    status: "protocol",
    note: "korekta po protokole",
    source: "manual",
    import_id: null,
    created_by_name: "Delivery Lead Przykładowy",
    updated_at: "2026-03-02T08:00:00Z",
  },
];

function renderDialog(props: { canEdit?: boolean } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <LineMonthlyHistoryDialog
        clientId={115}
        group={GROUP}
        line={LINE}
        canEdit={props.canEdit ?? true}
        open
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { invalidateSpy, onClose };
}

/** Radix zdejmuje `pointer-events` z body na czas modala. */
const setupUser = () => userEvent.setup({ pointerEventsCheck: 0 });

describe("LineMonthlyHistoryDialog — rozliczenia miesięczne linii MD", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(orderGroupsApi.listConsumptions).mockResolvedValue({ data: { rows: ROWS } } as never);
    vi.mocked(orderGroupsApi.putConsumption).mockResolvedValue({ data: LINE } as never);
    vi.mocked(orderGroupsApi.deleteConsumption).mockResolvedValue({ data: LINE } as never);
  });

  it("tabela: miesiąc po polsku, MD, etykieta statusu, źródło, autor, notatka i suma", async () => {
    renderDialog();

    const first = (await screen.findByText("gru 2025")).closest("tr")!;
    expect(first).toHaveTextContent("20");
    expect(first).toHaveTextContent(CONSUMPTION_STATUS_LABEL.accepted);
    expect(first).toHaveTextContent("import");
    expect(first).toHaveTextContent("Import z Finansów");

    const second = screen.getByText("lut 2026").closest("tr")!;
    expect(second).toHaveTextContent("18,5");
    expect(second).toHaveTextContent("Protokół");
    expect(second).toHaveTextContent("ręcznie");
    expect(second).toHaveTextContent("korekta po protokole");

    expect(screen.getByText("Razem").closest("tr")).toHaveTextContent("38,5");
    expect(orderGroupsApi.listConsumptions).toHaveBeenCalledWith(115, 910, 44);
  });

  it("nowy wpis idzie PUT-em po miesiącu i odświeża listę grup", async () => {
    const user = setupUser();
    const { invalidateSpy } = renderDialog();
    await screen.findByText("gru 2025");

    const save = screen.getByRole("button", { name: "Dodaj wpis" });
    // Bez miesiąca i MD zapis jest zablokowany — nie ma czego wysłać.
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText("Miesiąc *"), "2026-03");
    await user.type(screen.getByLabelText("MD *"), "21,5");
    await user.selectOptions(screen.getByLabelText("Status"), "protocol");
    await user.type(screen.getByLabelText("Notatka"), "protokół 03/2026");
    await user.click(save);

    await waitFor(() =>
      expect(orderGroupsApi.putConsumption).toHaveBeenCalledWith(115, 910, 44, "2026-03", {
        md_reported: 21.5,
        status: "protocol",
        note: "protokół 03/2026",
      }),
    );
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["client-order-groups", 115],
      }),
    );
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["order-line-consumptions", 115, 910, 44],
    });
  });

  it("edycja wpisu blokuje miesiąc — zmiana miesiąca założyłaby duplikat", async () => {
    const user = setupUser();
    renderDialog();
    await screen.findByText("gru 2025");

    await user.click(screen.getByRole("button", { name: "Edytuj wpis za gru 2025" }));
    expect(screen.getByLabelText("Miesiąc *")).toBeDisabled();
    expect(screen.getByLabelText("Miesiąc *")).toHaveValue("2025-12");
    expect(screen.getByLabelText("MD *")).toHaveValue("20");
    expect(screen.getByLabelText("Status")).toHaveValue("accepted");

    await user.clear(screen.getByLabelText("MD *"));
    await user.type(screen.getByLabelText("MD *"), "22");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() =>
      expect(orderGroupsApi.putConsumption).toHaveBeenCalledWith(115, 910, 44, "2025-12", {
        md_reported: 22,
        status: "accepted",
        note: null,
      }),
    );
  });

  it("usunięcie jest dwustopniowe: „Usuń” → „Potwierdź usunięcie” / „Anuluj”", async () => {
    const user = setupUser();
    renderDialog();
    const row = (await screen.findByText("lut 2026")).closest("tr")!;

    await user.click(within(row).getByRole("button", { name: "Usuń wpis za lut 2026" }));
    // Pierwsze kliknięcie NICZEGO nie kasuje.
    expect(orderGroupsApi.deleteConsumption).not.toHaveBeenCalled();
    await user.click(within(row).getByRole("button", { name: "Anuluj" }));
    expect(within(row).queryByRole("button", { name: "Potwierdź usunięcie" })).toBeNull();

    await user.click(within(row).getByRole("button", { name: "Usuń wpis za lut 2026" }));
    await user.click(within(row).getByRole("button", { name: "Potwierdź usunięcie" }));
    await waitFor(() =>
      expect(orderGroupsApi.deleteConsumption).toHaveBeenCalledWith(115, 910, 44, "2026-02"),
    );
  });

  it("bez uprawnień do obsady to sam podgląd — bez formularza i akcji", async () => {
    renderDialog({ canEdit: false });
    await screen.findByText("gru 2025");

    expect(screen.queryByRole("button", { name: "Dodaj wpis" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Usuń wpis/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Edytuj wpis/ })).toBeNull();
    expect(screen.queryByLabelText("Miesiąc *")).toBeNull();
  });

  it("pusty stan dopiero po SUKCESIE i z zaproszeniem do pierwszego wpisu", async () => {
    vi.mocked(orderGroupsApi.listConsumptions).mockResolvedValue({ data: { rows: [] } } as never);
    renderDialog();

    // Zanim odpowiedź dotrze, nie ma ani pustki, ani awarii.
    expect(screen.queryByText(/Brak wpisów miesięcznych/)).toBeNull();
    expect(
      await screen.findByText("Brak wpisów miesięcznych — dodaj pierwszy."),
    ).toBeInTheDocument();
  });

  it("awaria pobrania renderuje się jako błąd z ponowieniem, nie jako pustka", async () => {
    vi.mocked(orderGroupsApi.listConsumptions)
      .mockRejectedValueOnce(new Error("503"))
      .mockResolvedValueOnce({ data: { rows: ROWS } } as never);
    const user = setupUser();
    renderDialog();

    expect(
      await screen.findByText(/Nie udało się wczytać rozliczeń miesięcznych/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Brak wpisów miesięcznych/)).toBeNull();

    await user.click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    expect(await screen.findByText("gru 2025")).toBeInTheDocument();
  });
});
