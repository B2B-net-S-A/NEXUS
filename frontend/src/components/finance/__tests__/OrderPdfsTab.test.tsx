import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OrderPdfsTab } from "@/components/finance/OrderPdfsTab";
import { orderPdfStatusLabel } from "@/lib/finance-order-pdfs";

const getOrderPdfMonths = vi.fn();
const getOrderPdfs = vi.fn();

vi.mock("@/lib/api/finance", () => ({
  financeApi: {
    getOrderPdfMonths: (...args: unknown[]) => getOrderPdfMonths(...args),
    getOrderPdfs: (...args: unknown[]) => getOrderPdfs(...args),
  },
  orderPdfFilePath: vi.fn(),
  orderPdfZipPath: vi.fn(),
}));
vi.mock("@/components/v2/files/SearchablePdfPreview", () => ({
  SearchablePdfPreview: () => <div data-testid="pdf-preview" />,
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OrderPdfsTab />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  window.history.replaceState(null, "", "/finance");
  getOrderPdfMonths.mockReset();
  getOrderPdfs.mockReset();
});

describe("OrderPdfsTab — awaria listy klientów", () => {
  it("a failed client list is an error even when the month list failed too", async () => {
    // Miesiąc z adresu: lista klientów pyta serwer niezależnie od listy
    // miesięcy. Do 24.09.2026 jej błąd renderował się jako „W tym miesiącu
    // nie zaczyna się żadne zamówienie z PDF-em”, gdy lista miesięcy padła.
    window.history.replaceState(null, "", "/finance?view=order-pdfs&pdfMonth=2026-09");
    getOrderPdfMonths.mockRejectedValue(new Error("boom"));
    getOrderPdfs.mockRejectedValue(new Error("boom"));

    renderTab();

    await waitFor(() =>
      expect(screen.getAllByText("Nie udało się pobrać danych")).toHaveLength(2),
    );
    expect(
      screen.queryByText("W tym miesiącu nie zaczyna się żadne zamówienie z PDF-em."),
    ).toBeNull();
  });
});

describe("orderPdfStatusLabel", () => {
  it("names a cancelled order instead of printing the raw code", () => {
    expect(orderPdfStatusLabel("cancelled")).toBe("Anulowane");
    expect(orderPdfStatusLabel("exhausted")).toBe("Wyczerpane");
    expect(orderPdfStatusLabel("paused")).toBe("Wstrzymane");
    expect(orderPdfStatusLabel(null)).toBeNull();
  });
});
