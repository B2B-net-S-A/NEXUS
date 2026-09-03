import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/finance", () => ({
  financeApi: {
    listPeriods: vi.fn(),
    getResults: vi.fn(),
    updateRow: vi.fn(),
    importWorkbook: vi.fn(),
    listImports: vi.fn(),
    restoreImport: vi.fn(),
  },
}));

import { ToastProvider } from "@/components/Toast";
import { FinanceResultsTab } from "@/components/finance/FinanceResultsTab";
import { financeApi } from "@/lib/api/finance";

/**
 * Kolejność gałęzi stanu: awaria → „jeszcze nie wiem" → pustka → dane.
 *
 * Regresja z produkcji: warunek pustki brzmiał `periods.length === 0 &&
 * !isLoading`, więc stan „lista miesięcy się wczytuje" spadał do gałęzi
 * z danymi i rysował KOMPLETNY moduł na pustce — trzy kafle z „—" i pusty
 * selektor miesiąca. Czytało się to jak zaimportowany miesiąc bez ani jednej
 * złotówki, a nie jak „nic tu jeszcze nie ma".
 */

function renderTab(canWrite = true) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <FinanceResultsTab canWrite={canWrite} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("FinanceResultsTab — stany", () => {
  it("w trybie tylko do odczytu nie pokazuje importu", async () => {
    vi.mocked(financeApi.listPeriods).mockResolvedValue({ data: [] } as never);

    renderTab(false);

    expect(
      await screen.findByText("Nie zaimportowano jeszcze żadnego miesiąca."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Importuj plik Excel z wynikami"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Wgraj plik Excel powyżej/)).not.toBeInTheDocument();
  });

  it("w trakcie wczytywania NIE rysuje kafli ani selektora", async () => {
    // Zapytanie, które nigdy się nie kończy — utrwala stan „nie wiem jeszcze".
    vi.mocked(financeApi.listPeriods).mockReturnValue(
      new Promise(() => {}) as never,
    );

    renderTab();

    expect(await screen.findByText(/Ładowanie miesięcy/)).toBeInTheDocument();
    expect(screen.queryByText("KOSZT")).not.toBeInTheDocument();
    expect(screen.queryByText("PRZYCHÓD")).not.toBeInTheDocument();
    expect(screen.queryByText("MARŻA")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Miesiąc")).not.toBeInTheDocument();
    // I nie twierdzi jednocześnie, że nic nie zaimportowano.
    expect(
      screen.queryByText(/Nie zaimportowano jeszcze żadnego miesiąca/),
    ).not.toBeInTheDocument();
  });

  it("po pustej odpowiedzi mówi wprost, że nic nie zaimportowano", async () => {
    vi.mocked(financeApi.listPeriods).mockResolvedValue({ data: [] } as never);

    renderTab();

    expect(
      await screen.findByText(/Nie zaimportowano jeszcze żadnego miesiąca/),
    ).toBeInTheDocument();
    expect(screen.queryByText("KOSZT")).not.toBeInTheDocument();
  });

  it("awaria NIE renderuje się jako pustka", async () => {
    vi.mocked(financeApi.listPeriods).mockRejectedValue(new Error("boom"));

    renderTab();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.queryByText(/Nie zaimportowano jeszcze żadnego miesiąca/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("KOSZT")).not.toBeInTheDocument();
  });

  it("z danymi rysuje kafle, selektor i wiersze", async () => {
    vi.mocked(financeApi.listPeriods).mockResolvedValue({
      data: [
        { year: 2026, month: 8, label: "Sierpień 2026", run_id: 1, row_count: 1 },
      ],
    } as never);
    vi.mocked(financeApi.getResults).mockResolvedValue({
      data: {
        year: 2026,
        month: 8,
        run_id: 1,
        rows: [
          {
            id: 5,
            row_number: 2,
            consultant_name: "Adrian Kruk",
            client_name: "BNP Paribas",
            cost_rate_md: 950,
            md_count: 22.375,
            compensation: 20900.125,
            revenue_rate_md: 1190,
            invoice_amount: 26180,
            margin_pln: 5280,
            margin_pct: 20.2,
            edited_fields: [],
          },
        ],
        totals: { cost: 20900, revenue: 26180, margin: 5280, avg_margin_pct: 20.2 },
        needs_completion_count: 0,
      },
    } as never);

    renderTab();

    expect(await screen.findByText("Adrian Kruk")).toBeInTheDocument();
    expect(screen.getByText("22,375")).toBeInTheDocument();
    expect(screen.getByText(/20.*900,125 zł/)).toBeInTheDocument();
    expect(screen.getByText("KOSZT")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText("Miesiąc")).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/Nie zaimportowano jeszcze żadnego miesiąca/),
    ).not.toBeInTheDocument();
  });
});
