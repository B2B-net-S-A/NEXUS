import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditOrderDialog } from "@/components/EditOrderDialog";
import { ToastProvider } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";

vi.mock("@/lib/api/dlPortal", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/dlPortal")>();
  return {
    ...actual,
    dlPortalApi: {
      ...actual.dlPortalApi,
      extractOrderPdf: vi.fn(),
      updateOrder: vi.fn(),
      replaceOrderPo: vi.fn(),
      deleteOrderPo: vi.fn(),
    },
  };
});

const extractOrderPdf = vi.mocked(dlPortalApi.extractOrderPdf);

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <EditOrderDialog
          clientId={10}
          // Tryb „kontraktor bez zamówienia" (realny przypadek Banku
          // Pocztowego) — formularz pusty, szkic powstaje dopiero przy zapisie.
          order={null}
          onCreate={vi.fn()}
          rateCandidate={null}
          canManageFinance
          onClose={vi.fn()}
          onSaved={vi.fn()}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function addPdf(name = "zamowienie.pdf") {
  const input = screen.getByLabelText(/Zamień plik PDF/i);
  const file = new File(["dummy"], name, { type: "application/pdf" });
  fireEvent.change(input, { target: { files: [file] } });
  return file;
}

function extractBtn() {
  return screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i });
}

// ── Bank Pocztowy: stawka MD → godzinowa + „Sprawdź numer zamówienia" ────────
// Ten sam kontrakt odpowiedzi co w ExtendOrderDialog — ticket obejmuje OBA
// formularze widoku jednoosobowego („Uzupełnij zamówienie" i przedłużenie).

describe("EditOrderDialog — polityka Banku Pocztowego (odczyt PDF)", () => {
  beforeEach(() => {
    extractOrderPdf.mockReset();
  });

  it("pokazuje oryginał MD obok przeliczonej stawki godzinowej (edytowalnej)", async () => {
    extractOrderPdf.mockResolvedValue({
      data: {
        title: "BP/DIT/2026/0451",
        start_date: "2026-09-01",
        end_date: "2026-12-31",
        rate_client: 200,
        rate_unit: "hour",
        rate_client_md: 1600,
        total_value: null,
        currency: "PLN",
        md_total: null,
        uncertain: false,
        uncertain_reasons: [],
        fields_confidence: {},
        title_needs_review: false,
        source: "claude",
      },
    } as never);

    renderDialog();
    addPdf();
    fireEvent.click(extractBtn());

    await waitFor(() =>
      expect(screen.getByDisplayValue("200")).toBeInTheDocument(),
    );
    expect(screen.getByDisplayValue("BP/DIT/2026/0451")).toBeInTheDocument();
    expect(screen.getByText(/Z dokumentu: 1600 zł\/MD/)).toBeInTheDocument();
    // Czysty odczyt BP → bez banera „Sprawdź dane!".
    expect(screen.queryByText("Sprawdź dane!")).not.toBeInTheDocument();

    // Stawka godzinowa pozostaje edytowalna przed zapisem.
    fireEvent.change(screen.getByDisplayValue("200"), {
      target: { value: "205" },
    });
    expect(screen.getByDisplayValue("205")).toBeInTheDocument();
  });

  it("brak numeru → komunikat Sprawdź numer zamówienia, znika po wpisaniu", async () => {
    extractOrderPdf.mockResolvedValue({
      data: {
        title: null,
        start_date: "2026-09-01",
        end_date: "2026-12-31",
        rate_client: 200,
        rate_unit: "hour",
        rate_client_md: 1600,
        total_value: null,
        currency: null,
        md_total: null,
        uncertain: true,
        uncertain_reasons: [
          "Nie znaleziono pól „Numer pisma” ani „Zamówienie nr” — sprawdź numer zamówienia",
        ],
        fields_confidence: {},
        title_needs_review: true,
        source: "claude",
      },
    } as never);

    renderDialog();
    addPdf();
    fireEvent.click(extractBtn());

    await waitFor(() =>
      expect(screen.getByText("Sprawdź numer zamówienia")).toBeInTheDocument(),
    );
    // Komunikat z ticketu WYPIERA generyczne „wymagany" (nie dublują się).
    expect(
      screen.queryByText("Numer zamówienia jest wymagany."),
    ).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Numer zamówienia/), {
      target: { value: "BP/2026/77" },
    });
    expect(
      screen.queryByText("Sprawdź numer zamówienia"),
    ).not.toBeInTheDocument();
  });
});
