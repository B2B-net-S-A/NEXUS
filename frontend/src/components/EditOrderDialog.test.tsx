import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditOrderDialog } from "@/components/EditOrderDialog";
import { ToastProvider } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { ClientOrderRead, OrderType } from "@/lib/api/dlPortal";

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

function renderDialog({
  order = null,
  suggestedOrderType = "periodic",
  onCreate = vi.fn(),
}: {
  order?: ClientOrderRead | null;
  suggestedOrderType?: OrderType;
  onCreate?: ReturnType<typeof vi.fn>;
} = {}) {
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
          order={order}
          onCreate={onCreate}
          rateCandidate={null}
          canManageFinance
          suggestedOrderType={suggestedOrderType}
          onClose={vi.fn()}
          onSaved={vi.fn()}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function draftOrder(orderType: OrderType | null): ClientOrderRead {
  return {
    id: 41,
    client_id: 10,
    contract_id: 101,
    job_id: null,
    framework_contract_id: null,
    title: "DRAFT-41",
    description: null,
    status: "draft",
    order_type: orderType,
    start_date: null,
    end_date: null,
    rate_client: null,
    total_value: null,
    md_quantity: null,
    currency: "PLN",
    project_part: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    created_by_user_id: null,
    notes: null,
    created_at: "2026-08-27T10:00:00Z",
    updated_at: "2026-08-27T10:00:00Z",
    candidate_id: 1,
    candidate_name: "Jan Testowy",
    contract_status: "active",
    job_title: null,
    monthly_margin: null,
    days_to_end: null,
  };
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

describe("EditOrderDialog — jawny typ nowego draftu", () => {
  it("podpowiada typ z historii i jednym kliknięciem przełącza pola", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn().mockResolvedValue(77);
    renderDialog({ suggestedOrderType: "cost", onCreate });

    expect(screen.getByRole("radio", { name: "Kosztowe" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByLabelText(/Budżet całkowity/)).toBeInTheDocument();
    expect(screen.getByLabelText("Zafakturowano")).toHaveValue("0");

    await user.click(screen.getByRole("radio", { name: "MD" }));
    expect(screen.queryByLabelText(/Budżet całkowity/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Budżet w MD/)).toBeInTheDocument();
    expect(screen.getByLabelText("Wykorzystano MD")).toHaveValue("0");

    await user.click(screen.getByRole("radio", { name: "Okresowe" }));
    expect(screen.queryByLabelText(/Budżet całkowity/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Budżet w MD/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "MD" }));

    await user.type(screen.getByLabelText(/Numer zamówienia/), "MD-77");
    await user.type(screen.getByLabelText(/Budżet w MD/), "75,5");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    expect(onCreate.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        order_type: "md",
        md_quantity: 75.5,
        total_value: null,
      }),
    );
  });

  it("pozwala zmienić typ jawnego draftu, ale nie klasyfikuje starego draftu", () => {
    const { unmount } = renderDialog({ order: draftOrder("md") });
    expect(screen.getByRole("radiogroup", { name: "Typ zamówienia" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Budżet w MD/)).toBeInTheDocument();

    unmount();
    renderDialog({ order: draftOrder(null), suggestedOrderType: "cost" });
    expect(
      screen.queryByRole("radiogroup", { name: "Typ zamówienia" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Budżet całkowity/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Budżet w MD/)).not.toBeInTheDocument();
  });

  it("traktuje brak pola typu ze starszej odpowiedzi tak samo jak legacy NULL", () => {
    const legacyWithoutField = draftOrder(null);
    delete legacyWithoutField.order_type;

    renderDialog({ order: legacyWithoutField, suggestedOrderType: "md" });

    expect(
      screen.queryByRole("radiogroup", { name: "Typ zamówienia" }),
    ).not.toBeInTheDocument();
  });
});
