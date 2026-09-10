/**
 * Jednorazowe czyszczenie „Nieaktywnych klientów" — okno podglądu i raportu.
 *
 * Pilnujemy trzech rzeczy, które mają znaczenie przy trwałym kasowaniu:
 * (1) przycisk usunięcia jest nieaktywny, dopóki administrator nie potwierdzi,
 * a do serwera jedzie DOKŁADNIE lista z podglądu; (2) po wykonaniu (także
 * wcześniejszym) okno pokazuje raport z listą A i B zamiast drugiego
 * uruchomienia; (3) awaria podglądu jest awarią, a nie pustą listą.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  InactiveCleanupPreview,
  InactiveCleanupReport,
} from "@/lib/api";

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
  preview: vi.fn(),
  execute: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {},
  inactiveClientsCleanupApi: {
    status: () => mocks.status(),
    preview: () => mocks.preview(),
    execute: (ids: number[]) => mocks.execute(ids),
  },
}));

import { InactiveClientsCleanupDialog } from "@/components/clients/InactiveClientsCleanupDialog";

const SOURCE_LABELS = {
  active_projects: "Aktywne projekty",
  closed_projects: "Zamknięte projekty",
  archived_consultants: "Archiwalni konsultanci",
  orders: "Zamówienia",
  contracts: "Umowy / kontrakty",
  notes: "Notatki w profilu",
  sales_materials: "Materiały sprzedażowe",
  cooperation_stats: "Statystyki współpracy",
};

const PREVIEW: InactiveCleanupPreview = {
  evaluated_at: "2026-09-10T10:00:00+00:00",
  candidates_count: 3,
  to_delete: [
    {
      client_id: 11,
      name: "Pusta Sp. z o.o.",
      nip: "5250000000",
      external_source: "traffit",
      external_id: "901",
      sources: [],
      reasons: [],
    },
  ],
  held: [
    {
      client_id: 12,
      name: "Z Kontaktem SA",
      sources: [],
      reasons: [
        {
          code: "foreign_key",
          label: "Kontakty (osoby po stronie klienta)",
          count: 2,
          table: "contacts",
          effect: "blokują usunięcie",
        },
      ],
    },
  ],
  kept: [
    {
      client_id: 13,
      name: "Z Historią SA",
      sources: [{ code: "closed_projects", label: "Zamknięte projekty", count: 4 }],
      reasons: [],
    },
  ],
  kept_by_source: { closed_projects: 1 },
  source_labels: SOURCE_LABELS,
};

const REPORT: InactiveCleanupReport = {
  run_id: 1,
  executed_at: "2026-09-10T10:05:00+00:00",
  executed_by_name: "Artur Admin",
  candidates_count: 3,
  kept_count: 1,
  deleted_count: 1,
  held_count: 1,
  deleted: [{ client_id: 11, name: "Pusta Sp. z o.o.", nip: "5250000000" }],
  held: PREVIEW.held,
  summary: {},
};

function renderDialog(onExecuted = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <InactiveClientsCleanupDialog onClose={vi.fn()} onExecuted={onExecuted} />
    </QueryClientProvider>,
  );
  return { onExecuted };
}

describe("InactiveClientsCleanupDialog", () => {
  beforeEach(() => {
    mocks.status.mockReset();
    mocks.preview.mockReset();
    mocks.execute.mockReset();
  });

  it("wymaga potwierdzenia i wysyła dokładnie listę z podglądu", async () => {
    mocks.status.mockResolvedValue({
      data: { report: null, source_labels: SOURCE_LABELS },
    });
    mocks.preview.mockResolvedValue({ data: PREVIEW });
    mocks.execute.mockResolvedValue({ data: REPORT });
    const user = userEvent.setup();
    const { onExecuted } = renderDialog();

    expect(await screen.findByText("Pusta Sp. z o.o.")).toBeInTheDocument();
    // Lista B pokazuje, CO wstrzymało usunięcie.
    expect(screen.getByText("Z Kontaktem SA")).toBeInTheDocument();
    expect(
      screen.getByText("Kontakty (osoby po stronie klienta)"),
    ).toBeInTheDocument();

    const deleteButton = screen.getByRole("button", { name: /Usuń trwale \(1\)/ });
    expect(deleteButton).toBeDisabled();
    await user.click(deleteButton);
    expect(mocks.execute).not.toHaveBeenCalled();

    await user.click(screen.getByRole("checkbox"));
    expect(deleteButton).toBeEnabled();
    await user.click(deleteButton);

    await waitFor(() => expect(mocks.execute).toHaveBeenCalledWith([11]));
    expect(
      await screen.findByText("Lista A — klienci trwale usunięci"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Lista B — wstrzymani, do decyzji ręcznej"),
    ).toBeInTheDocument();
    expect(onExecuted).toHaveBeenCalledWith(
      "Czyszczenie zakończone: usunięto 1, wstrzymano 1.",
    );
    // Po wykonaniu nie ma już czym kliknąć drugi raz.
    expect(
      screen.queryByRole("button", { name: /Usuń trwale/ }),
    ).not.toBeInTheDocument();
  });

  it("po wcześniejszym wykonaniu pokazuje raport i nie prosi o podgląd", async () => {
    mocks.status.mockResolvedValue({
      data: { report: REPORT, source_labels: SOURCE_LABELS },
    });
    renderDialog();

    expect(
      await screen.findByText("Lista A — klienci trwale usunięci"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Artur Admin/)).toBeInTheDocument();
    expect(mocks.preview).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: /Usuń trwale/ }),
    ).not.toBeInTheDocument();
  });

  it("bez klientów do usunięcia nie oferuje wykonania (nie zużywa operacji)", async () => {
    mocks.status.mockResolvedValue({
      data: { report: null, source_labels: SOURCE_LABELS },
    });
    mocks.preview.mockResolvedValue({
      data: { ...PREVIEW, to_delete: [], candidates_count: 2 },
    });
    renderDialog();

    expect(
      await screen.findByText(/Nie ma klientów do usunięcia/),
    ).toBeInTheDocument();
    // Lista B nadal jest widoczna — decyzja ręczna nie czeka na wykonanie.
    expect(screen.getByText("Z Kontaktem SA")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Usuń trwale/ }),
    ).not.toBeInTheDocument();
  });

  it("awaria podglądu jest komunikatem, nie pustą listą", async () => {
    mocks.status.mockResolvedValue({
      data: { report: null, source_labels: SOURCE_LABELS },
    });
    mocks.preview.mockRejectedValue({
      response: { status: 500, data: { detail: "Baza nie odpowiada" } },
    });
    renderDialog();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Baza nie odpowiada",
    );
    expect(screen.queryByText("Do trwałego usunięcia")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Usuń trwale/ }),
    ).not.toBeInTheDocument();
  });
});
