import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { MdImportWorkspace } from "@/components/finance/MdImportWorkspace";
import type {
  ImportDetail,
  ImportRow,
  PolkomtelReprocessResponse,
} from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {},
  mdConsumptionApi: {
    listImports: vi.fn(),
    getImport: vi.fn(),
    upload: vi.fn(),
    assignRow: vi.fn(),
    reprocessPolkomtel: vi.fn(),
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

function reprocessResponse(
  overrides: Partial<PolkomtelReprocessResponse> = {},
): PolkomtelReprocessResponse {
  return {
    import_id: 1,
    period_month: "2026-07",
    client_id: 15,
    applied: false,
    rows_scanned: 2,
    rows_to_update: 1,
    targets_to_recalculate: 1,
    conflicts: [],
    targets: [
      {
        kind: "md_line",
        order_id: 321,
        group_id: 222,
        order_number: "SAP 1234567",
        row_ids: [71, 72],
        row_ids_to_update: [71],
        current_value: "1.125",
        expected_value: "2.375",
        write_required: true,
      },
    ],
    ...overrides,
  };
}

async function openUploadedImport(user: ReturnType<typeof userEvent.setup>) {
  vi.mocked(mdConsumptionApi.upload).mockResolvedValue({
    data: detail([row()]),
  } as never);

  await user.upload(
    screen.getByLabelText(/Plik XLSX/),
    new File(["x"], "raport.xlsx"),
  );
  await user.click(screen.getByRole("button", { name: /Importuj/ }));
  await screen.findByText(/Wynik importu/);
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
    vi.restoreAllMocks();
    vi.clearAllMocks();
    vi.mocked(mdConsumptionApi.listImports).mockResolvedValue({
      data: { imports: [] },
    } as never);
  });

  it("wyjaśnia dopasowanie wspólnej puli MD po numerze z Uwag", async () => {
    renderWorkspace();

    expect(
      await screen.findByText(/numer zamówienia z kolumny.*Uwagi/i),
    ).toBeInTheDocument();
  });

  it("pobiera do 100 historycznych importów, aby starszy miesiąc był osiągalny", async () => {
    renderWorkspace();

    await waitFor(() =>
      expect(mdConsumptionApi.listImports).toHaveBeenCalledWith(100),
    );
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

  it("pokazuje MD i kwotę importu do trzech miejsc z polskim separatorem", async () => {
    vi.mocked(mdConsumptionApi.upload).mockResolvedValue({
      data: detail([
        row({
          md_reported: 15.375,
          invoice_amount: 1234.125,
          cost_status: "applied",
          cost_status_label: "Rozliczono kwotę",
        }),
      ]),
    } as never);

    const user = userEvent.setup();
    renderWorkspace();

    await user.upload(
      screen.getByLabelText(/Plik XLSX/),
      new File(["x"], "raport.xlsx"),
    );
    await user.click(screen.getByRole("button", { name: /Importuj/ }));

    expect(await screen.findByText("15,375")).toBeInTheDocument();
    expect(screen.getByText(/1.*234,125/)).toBeInTheDocument();
  });

  it("pokazuje dokładny dry-run Polkomtela bez zapisywania zmian", async () => {
    vi.mocked(mdConsumptionApi.reprocessPolkomtel).mockResolvedValue({
      data: reprocessResponse(),
    } as never);

    const user = userEvent.setup();
    renderWorkspace();
    await openUploadedImport(user);

    await user.click(
      screen.getByRole("button", { name: "Sprawdź dopasowanie Polkomtel" }),
    );

    expect(mdConsumptionApi.reprocessPolkomtel).toHaveBeenCalledWith(1, false);
    expect(await screen.findByText("SAP 1234567")).toBeInTheDocument();
    expect(screen.getByText(/grupa #222, linia #321/)).toBeInTheDocument();
    expect(screen.getByText("ID: 71, 72")).toBeInTheDocument();
    expect(screen.getByText("Do korekty: 71")).toBeInTheDocument();
    expect(
      screen.getByText((_, element) =>
        element?.textContent === "1,125 MD → 2,375 MD",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Zastosuj sprawdzoną korektę" }),
    ).toBeEnabled();
  });

  it.each([
    {
      caseName: "konflikty",
      response: reprocessResponse({
        conflicts: ["Zamówienie SAP 1234567 ma nowsze ręczne rozliczenie."],
      }),
      expectedMessage: /nowsze ręczne rozliczenie/,
    },
    {
      caseName: "brak realnych zmian",
      response: reprocessResponse({
        rows_to_update: 0,
        targets_to_recalculate: 0,
        targets: [],
      }),
      expectedMessage: /Brak zmian do zastosowania/,
    },
  ])("nie udostępnia APPLY, gdy dry-run wykrywa $caseName", async ({ response, expectedMessage }) => {
    vi.mocked(mdConsumptionApi.reprocessPolkomtel).mockResolvedValue({
      data: response,
    } as never);

    const user = userEvent.setup();
    renderWorkspace();
    await openUploadedImport(user);
    await user.click(
      screen.getByRole("button", { name: "Sprawdź dopasowanie Polkomtel" }),
    );

    expect(await screen.findByText(expectedMessage)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Zastosuj sprawdzoną korektę" }),
    ).not.toBeInTheDocument();
  });

  it("wymaga jawnego potwierdzenia przed APPLY", async () => {
    const preview = reprocessResponse();
    vi.mocked(mdConsumptionApi.reprocessPolkomtel)
      .mockResolvedValueOnce({ data: preview } as never)
      .mockResolvedValueOnce({ data: { ...preview, applied: true } } as never);
    vi.mocked(mdConsumptionApi.getImport).mockResolvedValue({
      data: detail([row()]),
    } as never);
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);

    const user = userEvent.setup();
    renderWorkspace();
    await openUploadedImport(user);
    await user.click(
      screen.getByRole("button", { name: "Sprawdź dopasowanie Polkomtel" }),
    );

    const applyButton = await screen.findByRole("button", {
      name: "Zastosuj sprawdzoną korektę",
    });
    await user.click(applyButton);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(mdConsumptionApi.reprocessPolkomtel).toHaveBeenCalledTimes(1);

    await user.click(applyButton);
    expect(confirm).toHaveBeenCalledTimes(2);
    await waitFor(() =>
      expect(mdConsumptionApi.reprocessPolkomtel).toHaveBeenLastCalledWith(1, true),
    );
    expect(
      await screen.findByText(/Korekta została zastosowana/),
    ).toBeInTheDocument();
  });

  it("po konflikcie 409 usuwa stary plan i pokazuje aktualną listę konfliktów", async () => {
    const preview = reprocessResponse();
    vi.mocked(mdConsumptionApi.reprocessPolkomtel)
      .mockResolvedValueOnce({ data: preview } as never)
      .mockRejectedValueOnce({
        response: {
          status: 409,
          data: {
            detail: {
              code: "polkomtel_reprocess_conflict",
              conflicts: ["Wiersz 71 został ręcznie przypisany po analizie."],
            },
          },
        },
      });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const user = userEvent.setup();
    renderWorkspace();
    await openUploadedImport(user);
    await user.click(
      screen.getByRole("button", { name: "Sprawdź dopasowanie Polkomtel" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Zastosuj sprawdzoną korektę" }),
    );

    expect(
      await screen.findByText(/Wiersz 71 został ręcznie przypisany/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Podgląd korekty Polkomtel")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Zastosuj sprawdzoną korektę" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText(/uruchom analizę ponownie/i).length).toBeGreaterThan(0);
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
