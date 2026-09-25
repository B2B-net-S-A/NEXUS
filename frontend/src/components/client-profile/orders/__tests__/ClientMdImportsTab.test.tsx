import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClientMdImportsTab } from "@/components/client-profile/orders/ClientMdImportsTab";
import type { ClientMdImportDetail, ClientMdImportSummary } from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: { listClientMdImports: vi.fn(), getClientMdImport: vi.fn() },
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

const SUMMARY: ClientMdImportSummary = {
  id: 2,
  period_month: "2026-08",
  filename: "zuzycie_MD_sierpien.xlsx",
  created_at: "2026-09-23T11:40:03Z",
  uploaded_by_name: "Anna Korycka",
  rows_total: 3,
  rows_booked: 2,
  rows_to_verify: 1,
  rows_error: 0,
  md_booked: 25,
};

const DETAIL: ClientMdImportDetail = {
  ...SUMMARY,
  rows: [
    {
      id: 1,
      row_number: 35,
      consultant_name: "Paweł Łaski",
      order_number_hint: "4500030197",
      target_order_number: "4500030197",
      target_group_id: 51,
      md_reported: 2,
      invoice_amount: null,
      state: "booked",
      state_label: "Zaksięgowano",
      status_label: "Zaktualizowano",
      status_reason: null,
      number_mismatch: false,
    },
    {
      id: 2,
      row_number: 36,
      consultant_name: "Paweł Łaski",
      order_number_hint: "4500030845",
      target_order_number: "4500030197",
      target_group_id: 51,
      md_reported: 19,
      invoice_amount: null,
      state: "booked",
      state_label: "Zaksięgowano",
      status_label: "Zaktualizowano",
      status_reason: null,
      number_mismatch: true,
    },
    {
      id: 3,
      row_number: 40,
      consultant_name: "Marta Nowak",
      order_number_hint: null,
      target_order_number: null,
      target_group_id: null,
      md_reported: 20,
      invoice_amount: null,
      state: "to_verify",
      state_label: "Do weryfikacji",
      status_label: "Wymaga przypisania",
      status_reason: null,
      number_mismatch: false,
    },
  ],
};

function renderTab(selected: number | null, onSelect = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ClientMdImportsTab clientId={18} selectedImportId={selected} onSelectImport={onSelect} />
    </QueryClientProvider>,
  );
  return onSelect;
}

describe("ClientMdImportsTab — zakładka „Importy MD”", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(orderGroupsApi.listClientMdImports).mockResolvedValue({
      data: { imports: [SUMMARY] },
    } as never);
    vi.mocked(orderGroupsApi.getClientMdImport).mockResolvedValue({ data: DETAIL } as never);
  });

  it("lista: miesiąc, data i autor, plik, wiersze / zaksięgowane / do weryfikacji", async () => {
    const onSelect = renderTab(null);
    const item = await screen.findByRole("button", { name: /Otwórz import MD za sierpień 2026/ });
    expect(item).toHaveTextContent("sierpień 2026");
    expect(item).toHaveTextContent("Anna Korycka");
    expect(item).toHaveTextContent("zuzycie_MD_sierpien.xlsx");
    expect(item).toHaveTextContent("wierszy: 3");
    expect(item).toHaveTextContent("zaksięgowano: 2");
    expect(item).toHaveTextContent("do weryfikacji: 1");
    await userEvent.click(item);
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("otwarty import: wiersze ze statusem, wyróżniony wiersz z innym numerem", async () => {
    const onSelect = renderTab(2);
    const mismatch = (await screen.findByText("36")).closest("tr")!;
    expect(mismatch).toHaveAttribute("data-mismatch", "true");
    expect(mismatch).toHaveTextContent("4500030845");
    expect(mismatch).toHaveTextContent("inny numer");
    expect(mismatch).toHaveTextContent("4500030197");
    expect(screen.getByText("35").closest("tr")).not.toHaveAttribute("data-mismatch");
    const pending = screen.getByText("40").closest("tr")!;
    expect(within(pending).getByText("Do weryfikacji")).toBeInTheDocument();
    expect(pending).toHaveTextContent("Wymaga przypisania");
    expect(orderGroupsApi.getClientMdImport).toHaveBeenCalledWith(18, 2);

    await userEvent.click(screen.getByRole("button", { name: /Wszystkie importy/ }));
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("brak importów klienta to komunikat, nie pusta ramka", async () => {
    vi.mocked(orderGroupsApi.listClientMdImports).mockResolvedValue({
      data: { imports: [] },
    } as never);
    renderTab(null);
    expect(
      await screen.findByText("Żaden import MD nie dotyczył jeszcze zamówień tego klienta."),
    ).toBeInTheDocument();
  });
});
