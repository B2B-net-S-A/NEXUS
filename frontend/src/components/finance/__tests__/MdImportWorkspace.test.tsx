import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { MdImportWorkspace } from "@/components/finance/MdImportWorkspace";
import type { ImportDetail, ImportRow } from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {},
  mdConsumptionApi: {
    listImports: vi.fn(),
    getImport: vi.fn(),
    upload: vi.fn(),
    assignRow: vi.fn(),
  },
}));

import { mdConsumptionApi } from "@/lib/api/orderGroups";

function row(overrides: Partial<ImportRow> = {}): ImportRow {
  return {
    id: 1,
    row_number: 2,
    consultant_name: "Jan Kowalski",
    md_reported: 15,
    status: "applied",
    status_label: "Zaktualizowano",
    matched_order_id: 99,
    matched: {
      order_id: 99,
      order_number: "445",
      client_id: 7,
      client_name: "BIK",
      consultant_name: "Jan Kowalski",
      md_remaining: 35,
    },
    options: [],
    resolved_at: null,
    notes_raw: null,
    order_number_hint: null,
    invoice_amount: null,
    cost_status: null,
    cost_status_label: null,
    ...overrides,
  };
}

function detail(rows: ImportRow[]): ImportDetail {
  return {
    id: 1,
    period_month: "2026-07",
    filename: "raport.xlsx",
    rows_total: rows.length,
    rows_applied: rows.filter((r) => r.status === "applied").length,
    rows_ambiguous: rows.filter((r) => r.status === "needs_assignment").length,
    rows_cost_applied: 0,
  rows_cost_unmatched: 0,
  rows_unmatched: rows.filter((r) => r.status === "unmatched").length,
    uploaded_by_user_id: 1,
    created_at: "2026-07-01T10:00:00Z",
    rows,
    skipped_rows: [],
    sheet_name: "Dane",
  };
}

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MdImportWorkspace />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("MdImportWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(mdConsumptionApi.listImports).mockResolvedValue({
      data: { imports: [] },
    } as never);
  });

  it("wiersz niejednoznaczny czeka na wybór i NIE jest zastosowany sam", async () => {
    const ambiguous = row({
      status: "needs_assignment",
      status_label: "Wymaga przypisania",
      matched_order_id: null,
      matched: null,
      options: [
        {
          order_id: 99,
          order_number: "445",
          client_id: 7,
          client_name: "BIK",
          consultant_name: "Jan Kowalski",
          md_remaining: 35,
        },
        {
          order_id: 100,
          order_number: "512",
          client_id: 8,
          client_name: "Polkomtel",
          consultant_name: "Jan Kowalski",
          md_remaining: 20,
        },
      ],
    });
    vi.mocked(mdConsumptionApi.upload).mockResolvedValue({
      data: detail([ambiguous]),
    } as never);
    vi.mocked(mdConsumptionApi.assignRow).mockResolvedValue({ data: {} } as never);
    vi.mocked(mdConsumptionApi.getImport).mockResolvedValue({
      data: detail([row()]),
    } as never);

    const user = userEvent.setup();
    renderWorkspace();

    const file = new File(["x"], "raport.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await user.upload(screen.getByLabelText(/Plik XLSX/), file);
    await user.click(screen.getByRole("button", { name: /Importuj/ }));

    expect(await screen.findByText("Wymaga przypisania")).toBeInTheDocument();
    expect(
      screen.getByText(/System nie\s+wybiera za Ciebie/),
    ).toBeInTheDocument();

    const select = screen.getByRole("combobox", {
      name: /Wybierz zamówienie dla Jan Kowalski/,
    });
    expect(select).toBeInTheDocument();

    // Przycisk „Przypisz" jest nieaktywny, dopóki operator nie wskaże zamówienia.
    const assign = screen.getByRole("button", { name: "Przypisz" });
    expect(assign).toBeDisabled();

    await user.selectOptions(select, "100");
    expect(assign).toBeEnabled();
    await user.click(assign);

    await waitFor(() =>
      expect(mdConsumptionApi.assignRow).toHaveBeenCalledWith(1, 1, 100),
    );
  });

  it("wiersz bez dopasowania jest oznaczony, a nie pominięty", async () => {
    vi.mocked(mdConsumptionApi.upload).mockResolvedValue({
      data: detail([
        row({
          id: 2,
          status: "unmatched",
          status_label: "Brak aktywnego zamówienia",
          matched_order_id: null,
          matched: null,
          consultant_name: "Nikt Taki",
        }),
        row(),
      ]),
    } as never);

    const user = userEvent.setup();
    renderWorkspace();

    await user.upload(
      screen.getByLabelText(/Plik XLSX/),
      new File(["x"], "raport.xlsx"),
    );
    await user.click(screen.getByRole("button", { name: /Importuj/ }));

    expect(await screen.findByText("Brak aktywnego zamówienia")).toBeInTheDocument();
    expect(screen.getByText("Nikt Taki")).toBeInTheDocument();
    // Pozostałe wiersze przeszły mimo jednego bez dopasowania.
    expect(screen.getByText("Zaktualizowano")).toBeInTheDocument();
  });

  it("odrzuca plik o złym rozszerzeniu zanim poleci request", async () => {
    renderWorkspace();

    // `fireEvent`, nie `user.upload`: `userEvent` honoruje atrybut `accept`
    // i w ogóle nie odpaliłby zdarzenia, więc test sprawdzałby atrybut HTML
    // zamiast naszego guardu. Atrybut `accept` jest podpowiedzią dla okna
    // wyboru pliku — użytkownik obchodzi go opcją „Wszystkie pliki".
    const input = screen.getByLabelText(/Plik XLSX/) as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "raport.csv", { type: "text/csv" })] },
    });

    expect(
      await screen.findByText("Dozwolone są tylko pliki XLSX."),
    ).toBeInTheDocument();
    expect(mdConsumptionApi.upload).not.toHaveBeenCalled();
  });

  it("historia w trakcie pobierania nie udaje pustej listy", async () => {
    vi.mocked(mdConsumptionApi.listImports).mockReturnValue(
      new Promise(() => {}) as never,
    );

    renderWorkspace();

    expect(await screen.findByText("Wczytywanie…")).toBeInTheDocument();
    expect(screen.queryByText("Brak importów")).not.toBeInTheDocument();
  });

  it("awaria historii importów renderuje błąd, nie pustkę", async () => {
    vi.mocked(mdConsumptionApi.listImports).mockRejectedValue(new Error("boom"));

    renderWorkspace();

    expect(
      await screen.findByText(/Nie udało się wczytać historii importów/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Brak importów")).not.toBeInTheDocument();
  });
});
