import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditOrderDialog } from "@/components/EditOrderDialog";
import { ToastProvider } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { ClientOrderRead, OrderType } from "@/lib/api/dlPortal";
import type { LegacyClientOrderType } from "@/lib/client-order-list";

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
const updateOrder = vi.mocked(dlPortalApi.updateOrder);

function renderDialog({
  order = null,
  suggestedOrderType = "periodic",
  legacyNullOrderType = "periodic",
  onCreate = vi.fn(),
  rateCandidate = null,
  contractRateUnit = "monthly",
  contractRateClientCurrency = "PLN",
  contractRateCandidateCurrency = "PLN",
}: {
  order?: ClientOrderRead | null;
  suggestedOrderType?: OrderType;
  legacyNullOrderType?: LegacyClientOrderType;
  onCreate?: ReturnType<typeof vi.fn>;
  rateCandidate?: number | null;
  contractRateUnit?: "hourly" | "daily" | "monthly";
  contractRateClientCurrency?: string | null;
  contractRateCandidateCurrency?: string | null;
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <EditOrderDialog
          clientId={10}
          candidateId={1}
          // Tryb „kontraktor bez zamówienia" (realny przypadek Banku
          // Pocztowego) — formularz pusty, szkic powstaje dopiero przy zapisie.
          order={order}
          onCreate={onCreate}
          rateCandidate={rateCandidate}
          contractRateUnit={contractRateUnit}
          contractRateClientCurrency={contractRateClientCurrency}
          contractRateCandidateCurrency={contractRateCandidateCurrency}
          canManageFinance
          suggestedOrderType={suggestedOrderType}
          legacyNullOrderType={legacyNullOrderType}
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
    updateOrder.mockReset();
    updateOrder.mockResolvedValue({ data: {} } as never);
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
    expect(screen.getByText(/Z dokumentu: 1600 PLN\/MD/)).toBeInTheDocument();
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

describe("EditOrderDialog — jednostka i waluta zamówienia", () => {
  beforeEach(() => {
    extractOrderPdf.mockReset();
    updateOrder.mockReset();
    updateOrder.mockResolvedValue({ data: {} } as never);
  });

  it("przekazuje candidate_id do odczytu, wykrywa MD i wysyła przeliczone stawki", async () => {
    const order = draftOrder("periodic");
    order.rate_candidate = 125;
    order.rate_client = 150;
    order.rate_unit = "hourly";
    order.currency = "EUR";
    order.rate_client_currency = "EUR";
    order.rate_candidate_currency = "GBP";
    extractOrderPdf.mockResolvedValue({
      data: {
        title: "PO-MD-1",
        start_date: null,
        end_date: null,
        rate_client: 1320,
        rate_unit: "day",
        total_value: null,
        currency: "USD",
        md_total: null,
        uncertain: false,
        uncertain_reasons: [],
        fields_confidence: {},
        source: "claude",
      },
    } as never);

    renderDialog({ order });
    const file = addPdf();
    fireEvent.click(extractBtn());

    await waitFor(() =>
      expect(extractOrderPdf).toHaveBeenCalledWith(10, file, 1),
    );
    expect(screen.getByLabelText("Stawka kosztowa")).toHaveValue("1000");
    expect(screen.getByLabelText("Stawka przychodowa")).toHaveValue("1320");
    expect(
      within(
        screen.getByRole("radiogroup", { name: "Jednostka stawki" }),
      ).getByRole("radio", { name: "MD" }),
    ).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(
      screen.getByRole("combobox", {
        name: "Waluta zamówienia (przychodowa)",
      }),
    ).toHaveValue("USD");
    expect(
      screen.getByRole("combobox", { name: "Waluta stawki kosztowej" }),
    ).toHaveValue("GBP");
    expect(
      screen.getByText(
        "Jednostkę stawki zmieniono na MD na podstawie odczytanej pozycji",
      ),
    ).toHaveAttribute("role", "status");

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(updateOrder).toHaveBeenCalledOnce());
    expect(updateOrder).toHaveBeenCalledWith(
      10,
      41,
      expect.objectContaining({
        rate_candidate: 1000,
        rate_client: 1320,
        rate_unit: "daily",
        rate_client_currency: "USD",
        rate_candidate_currency: "GBP",
      }),
    );
    expect(updateOrder.mock.calls[0]?.[2]).not.toHaveProperty("currency");
  });

  it("pokazuje brutto i netto PFRON/Erste oraz resetuje informację z nowym plikiem", async () => {
    const order = draftOrder("periodic");
    order.rate_unit = "hourly";
    extractOrderPdf.mockResolvedValue({
      data: {
        title: "PFRON-1",
        start_date: null,
        end_date: null,
        rate_client: 100,
        rate_client_gross: 123,
        rate_unit: "hour",
        total_value: null,
        currency: "PLN",
        md_total: null,
        uncertain: false,
        uncertain_reasons: [],
        fields_confidence: {},
        source: "claude",
      },
    } as never);

    renderDialog({ order });
    addPdf();
    fireEvent.click(extractBtn());

    expect(
      await screen.findByText(/123 PLN\/h brutto.*100 PLN\/h netto/),
    ).toBeInTheDocument();
    addPdf("nowy.pdf");
    expect(screen.queryByText(/PLN\/h brutto/)).not.toBeInTheDocument();
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

    const typeSwitch = screen.getByRole("radiogroup", {
      name: "Typ zamówienia",
    });
    await user.click(within(typeSwitch).getByRole("radio", { name: "MD" }));
    expect(screen.queryByLabelText(/Budżet całkowity/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Budżet w MD/)).toBeInTheDocument();
    expect(screen.getByLabelText("Wykorzystano MD")).toHaveValue("0");

    await user.click(
      within(typeSwitch).getByRole("radio", { name: "Okresowe" }),
    );
    expect(screen.queryByLabelText(/Budżet całkowity/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Budżet w MD/)).not.toBeInTheDocument();
    await user.click(within(typeSwitch).getByRole("radio", { name: "MD" }));

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

  it("pokazuje legacy NULL jako MD tylko w kontekście klienta bez periodic", () => {
    const { unmount } = renderDialog({
      order: draftOrder(null),
      suggestedOrderType: "cost",
      legacyNullOrderType: "md",
    });

    expect(
      screen.queryByRole("radiogroup", { name: "Typ zamówienia" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Budżet w MD/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Budżet całkowity/)).not.toBeInTheDocument();

    unmount();
    renderDialog({
      order: draftOrder(null),
      suggestedOrderType: "md",
    });
    expect(screen.queryByLabelText(/Budżet w MD/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Budżet całkowity/)).not.toBeInTheDocument();
  });
});
