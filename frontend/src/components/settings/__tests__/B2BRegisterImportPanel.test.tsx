import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { B2BRegisterImportPanel } from "@/components/settings/B2BRegisterImportPanel";

const mocks = vi.hoisted(() => ({
  registerImport: vi.fn(),
  registerImportRuns: vi.fn(),
  rollbackRegisterImport: vi.fn(),
  exportRegisterXlsx: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ b2bGeneratorApi: mocks }));

function report(mode: "dry_run" | "applied") {
  return {
    run_id: 7,
    mode,
    filename: "rejestr.xlsx",
    sha256: "a".repeat(64),
    no_business_sheet_found: true,
    counters: {
      rows_total: 3,
      contract_rows: 3,
      created: 2,
      updated: 1,
      unchanged: 0,
      skipped: 0,
      cancelled: 0,
      closed: 0,
      likely_ended: 0,
      generator_matches: 0,
      generator_discrepancies: 1,
      number_collisions: 0,
      missing_marked: 0,
      status_kept: 0,
      candidates_matched: 1,
      candidates_unmatched: 0,
      candidates_ambiguous: 0,
      clients_matched: 3,
      clients_internal: 0,
      clients_unknown_rows: 0,
      recruiters_matched: 0,
      recruiters_unknown_rows: 0,
      annex_rows: 0,
      annex_matched: 0,
      annex_unmatched: 0,
      annex_done: 0,
    },
    unmatched_candidates: [],
    ambiguous_candidates: [],
    unknown_clients: [],
    unknown_recruiters: [],
    generator_discrepancies: [
      {
        row: 5,
        number: "1518/2026",
        excel_partner: "Anna Testowa",
        nexus_partner: "Jan Próbny",
        excel_client: "Klient A",
        nexus_client: "Klient A",
        differences: ["partner"],
      },
    ],
    number_collisions: [],
    status_kept: [],
    annex: { matched: [], unmatched: [] },
    skipped_rows: [],
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <B2BRegisterImportPanel />
    </QueryClientProvider>,
  );
}

function pickFile() {
  const input = screen.getByLabelText("Plik rejestru umów (.xlsx)");
  const file = new File(["x"], "rejestr.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  fireEvent.change(input, { target: { files: [file] } });
  return file;
}

// Maszyna CI/dev bywa przeciążona — dłuższe czekanie na zapytania nie zmienia
// tego, co test sprawdza.
const WAIT = { timeout: 15_000 };

describe("B2BRegisterImportPanel", { timeout: 60_000 }, () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.registerImportRuns.mockResolvedValue([]);
  });

  it("„Zastosuj” jest dostępne dopiero po podglądzie tego samego pliku", async () => {
    mocks.registerImport.mockImplementation((_file: File, dryRun: boolean) =>
      Promise.resolve(report(dryRun ? "dry_run" : "applied")),
    );
    renderPanel();
    const apply = screen.getByRole("button", { name: "Zastosuj" });
    expect(apply).toBeDisabled();

    const file = pickFile();
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Podgląd/ }));

    await screen.findByText("Podgląd — nic nie zostało zapisane.", { exact: false }, WAIT);
    expect(screen.getByText(/Rozbieżności z NEXUSEM \(1\)/)).toBeInTheDocument();
    await waitFor(() => expect(apply).toBeEnabled(), WAIT);

    fireEvent.click(apply);
    await screen.findByText("Zapisano: 2 nowych, 1 zmienionych.", undefined, WAIT);
    expect(mocks.registerImport).toHaveBeenLastCalledWith(file, false);
  });

  it("błąd importu pokazuje komunikat serwera, nie pusty raport", async () => {
    mocks.registerImport.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { detail: "Nie znaleziono arkusza „Umowy B2B”." } },
    });
    renderPanel();
    pickFile();
    fireEvent.click(screen.getByRole("button", { name: /Podgląd/ }));
    expect(await screen.findByRole("alert", undefined, WAIT)).toHaveTextContent("Nie znaleziono arkusza");
    expect(screen.queryByTestId("register-import-report")).toBeNull();
  });

  it("awaria listy przebiegów nie wygląda jak brak przebiegów", async () => {
    mocks.registerImportRuns.mockRejectedValue(new Error("boom"));
    renderPanel();
    expect(await screen.findByText("Nie udało się pobrać danych", undefined, WAIT)).toBeInTheDocument();
    expect(screen.queryByText("Nie było jeszcze żadnego importu.")).toBeNull();
  });

  it("„Cofnij” pyta w oknie i woła API dla ostatniego przebiegu", async () => {
    mocks.registerImportRuns.mockResolvedValue([
      {
        id: 12,
        mode: "applied",
        filename: "rejestr.xlsx",
        sha256: "b".repeat(64),
        counters: { created: 4, updated: 2 },
        created_at: "2026-09-23T10:00:00+00:00",
        created_by_name: "Admin",
        rolled_back_at: null,
        can_rollback: true,
      },
    ]);
    mocks.rollbackRegisterImport.mockResolvedValue({
      run_id: 12,
      deleted: 4,
      restored: 2,
      missing_cleared: 0,
    });
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /Cofnij$/ }, WAIT));
    fireEvent.click(await screen.findByRole("button", { name: "Cofnij przebieg" }, WAIT));
    await screen.findByText("Cofnięto przebieg: usunięto 4, przywrócono 2.", undefined, WAIT);
    expect(mocks.rollbackRegisterImport).toHaveBeenCalledWith(12);
  });
});
