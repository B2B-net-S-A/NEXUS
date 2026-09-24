import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/finance", () => ({
  financeApi: {
    listImports: vi.fn(),
    restoreImport: vi.fn(),
  },
}));

vi.mock("@/lib/authenticated-files", () => ({
  downloadAuthenticatedFile: vi.fn(),
}));

import { ToastProvider } from "@/components/Toast";
import { FinanceArchiveTab } from "@/components/finance/FinanceArchiveTab";
import { financeApi } from "@/lib/api/finance";

function renderTab(canWrite: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <FinanceArchiveTab canWrite={canWrite} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(financeApi.listImports).mockResolvedValue({
    data: [
      {
        id: 7,
        year: 2026,
        month: 8,
        label: "Sierpień 2026",
        status: "superseded",
        source_filename: "wyniki.xlsx",
        size_bytes: 2048,
        row_count: 3,
        needs_completion_count: 0,
        rejected_count: 0,
        created_at: "2026-08-31T10:00:00Z",
        superseded_at: "2026-09-01T10:00:00Z",
        created_by_email: "finance@example.com",
      },
    ],
  } as never);
});

describe("FinanceArchiveTab section access", () => {
  it("ukrywa przywracanie wersji przy dostępie tylko do odczytu", async () => {
    renderTab(false);

    expect(await screen.findByText("Sierpień 2026")).toBeInTheDocument();
    expect(screen.getByTitle("Pobierz oryginalny plik")).toBeInTheDocument();
    expect(screen.queryByTitle("Przywróć jako aktualny")).not.toBeInTheDocument();
  });

  it("pokazuje przywracanie wersji przy prawie zapisu", async () => {
    renderTab(true);

    expect(await screen.findByTitle("Przywróć jako aktualny")).toBeInTheDocument();
  });
});

describe("FinanceArchiveTab — przywrócenie wersji", () => {
  it("pyta w oknie aplikacji, nie natywnym confirm (zamraża automatyzację)", async () => {
    const nativeConfirm = vi.spyOn(window, "confirm");
    vi.mocked(financeApi.restoreImport).mockResolvedValue({ data: {} } as never);
    renderTab(true);

    fireEvent.click(await screen.findByTitle("Przywróć jako aktualny"));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Sierpień 2026");
    expect(nativeConfirm).not.toHaveBeenCalled();
    expect(financeApi.restoreImport).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Przywróć" }));
    await waitFor(() => expect(financeApi.restoreImport).toHaveBeenCalledWith(7));
    nativeConfirm.mockRestore();
  });

  it("anulowanie okna niczego nie przywraca", async () => {
    renderTab(true);

    fireEvent.click(await screen.findByTitle("Przywróć jako aktualny"));
    fireEvent.click(await screen.findByRole("button", { name: "Anuluj" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(financeApi.restoreImport).not.toHaveBeenCalled();
  });
});
