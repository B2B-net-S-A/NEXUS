import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExtendOrderDialog } from "@/components/ExtendOrderDialog";
import { ToastProvider } from "@/components/Toast";
import {
  dlPortalApi,
  type ContractWithOrdersRead,
} from "@/lib/api/dlPortal";
import { useAuthStore, type User } from "@/store/auth";

vi.mock("@/lib/api/dlPortal", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/dlPortal")>();
  return {
    ...actual,
    dlPortalApi: {
      ...actual.dlPortalApi,
      createOrderExtension: vi.fn(),
      extractOrderPdf: vi.fn(),
    },
  };
});

const createOrderExtension = vi.mocked(dlPortalApi.createOrderExtension);
const extractOrderPdf = vi.mocked(dlPortalApi.extractOrderPdf);

function user(role: "admin" | "delivery_lead"): User {
  return {
    id: role === "admin" ? 1 : 17,
    email: `${role}@example.com`,
    name: role,
    role,
    roles: [role],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    capabilities: role === "admin" ? ["manage_finance"] : ["view_client_operations"],
  };
}

const contract: ContractWithOrdersRead = {
  contract_id: 101,
  candidate_id: 7,
  candidate_name: "Jan Kowalski",
  contract_status: "active",
  contract_start_date: "2026-01-01",
  contract_end_date: null,
  // Intentionally populated to prove the UI does not trust a stale/leaky cache.
  rate_candidate: 12_000,
  rate_client_currency: "PLN",
  rate_candidate_currency: "PLN",
  rate_unit: "monthly",
  initial_job_id: 44,
  initial_job_title: "Backend Engineer",
  latest_order_id: null,
  latest_order_end_date: null,
  latest_order_rate_client: 18_000,
  latest_order_monthly_margin: 6_000,
  days_to_latest_end: null,
  orders: [],
};

function renderDialog(
  contractValue: ContractWithOrdersRead = contract,
  canManageFinance?: boolean,
) {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ExtendOrderDialog
          clientId={10}
          contract={contractValue}
          canManageFinance={canManageFinance}
          onClose={vi.fn()}
          onCreated={vi.fn()}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("ExtendOrderDialog candidate finance lockdown", () => {
  beforeEach(() => {
    createOrderExtension.mockReset();
    createOrderExtension.mockResolvedValue({ data: {} } as never);
  });

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, hydrated: true });
    });
  });

  it("Delivery Lead nie widzi kwot i nie wysyła ich w FormData", async () => {
    act(() => {
      useAuthStore.setState({ user: user("delivery_lead"), hydrated: true });
    });
    renderDialog();

    expect(screen.queryByText(/Stawka przychodowa/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Stawka kosztowa/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Total value/)).not.toBeInTheDocument();
    expect(screen.queryByText(/marża/i)).not.toBeInTheDocument();

    // Numer zamówienia i data startu są teraz WYMAGANE, więc bez ich
    // wypełnienia formularz nie przechodzi walidacji i submit nie leci.
    // Ten fixture ma `orders: []`, więc data startu NIE jest prefillowana
    // z końca poprzedniego zamówienia — trzeba ją podać wprost.
    fireEvent.change(screen.getByLabelText(/Numer zamówienia/), {
      target: { value: "45767" },
    });
    fireEvent.change(screen.getByLabelText(/^Start/), {
      target: { value: "2026-09-01" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz przedłużenie" }));

    await waitFor(() => expect(createOrderExtension).toHaveBeenCalledOnce());
    const formData = createOrderExtension.mock.calls[0][1];
    expect(formData.has("rate_client")).toBe(false);
    expect(formData.has("rate_candidate")).toBe(false);
    expect(formData.has("rate_unit")).toBe(false);
    expect(formData.has("currency")).toBe(false);
    expect(formData.has("rate_client_currency")).toBe(false);
    expect(formData.has("rate_candidate_currency")).toBe(false);
    expect(formData.has("total_value")).toBe(false);
    expect(formData.get("contract_id")).toBe("101");
  });

  it("Admin z manage_finance widzi pola finansowe", () => {
    act(() => {
      useAuthStore.setState({ user: user("admin"), hydrated: true });
    });
    renderDialog();

    expect(screen.getByText(/Stawka przychodowa/)).toBeInTheDocument();
    expect(screen.getByText(/Stawka kosztowa/)).toBeInTheDocument();
    expect(screen.getByText(/Total value/)).toBeInTheDocument();
    expect(screen.getByText(/marża/i)).toBeInTheDocument();
  });

  it("przypisany Delivery Lead korzysta z serwerowego can_manage_finance", () => {
    act(() => {
      useAuthStore.setState({ user: user("delivery_lead"), hydrated: true });
    });
    renderDialog(contract, true);

    expect(screen.getByText(/Stawka przychodowa/)).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "Jednostka stawki" })).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", {
        name: "Waluta zamówienia (przychodowa)",
      }),
    ).toBeInTheDocument();
  });
});

function addPdf(name = "zamowienie.pdf") {
  const input = screen.getByLabelText(/PDF zamówienia od klienta/i);
  const file = new File(["dummy"], name, { type: "application/pdf" });
  fireEvent.change(input, { target: { files: [file] } });
  return file;
}

function extractBtn() {
  return screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i });
}

describe("ExtendOrderDialog — odczyt PDF (Zczytaj dane z dokumentu)", () => {
  beforeEach(() => {
    createOrderExtension.mockReset();
    createOrderExtension.mockResolvedValue({ data: {} } as never);
    extractOrderPdf.mockReset();
  });

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, hydrated: true });
    });
  });

  it("dodanie pliku NIE zmienia pól ani nie uruchamia odczytu (spec 1a)", () => {
    act(() => {
      useAuthStore.setState({ user: user("admin"), hydrated: true });
    });
    renderDialog();

    // Pole startuje PUSTE — autofill „Przedłużenie <imię>" został usunięty,
    // bo ta wartość jest pokazywana na karcie klienta jako „Numer zamówienia",
    // a podpowiedź wpisywała tam nazwisko.
    const titleInput = screen.getByLabelText(/Numer zamówienia/);
    expect(titleInput).toHaveValue("");
    addPdf();

    // Sam wybór pliku nie dotyka formularza i nie woła backendu.
    expect(titleInput).toHaveValue("");
    expect(extractOrderPdf).not.toHaveBeenCalled();
    expect(screen.queryByText("Sprawdź dane!")).not.toBeInTheDocument();
  });

  it("przycisk odczytu jest nieaktywny bez pliku, aktywny po dodaniu", () => {
    act(() => {
      useAuthStore.setState({ user: user("admin"), hydrated: true });
    });
    renderDialog();

    expect(extractBtn()).toBeDisabled();
    addPdf();
    expect(extractBtn()).toBeEnabled();
  });

  it("odczyt wypełnia pola i pokazuje baner 'Sprawdź dane!' przy uncertain", async () => {
    act(() => {
      useAuthStore.setState({ user: user("admin"), hydrated: true });
    });
    extractOrderPdf.mockResolvedValue({
      data: {
        title: "PO-123",
        start_date: "2026-06-01",
        end_date: "2026-12-31",
        rate_client: 17000,
        rate_unit: "month",
        total_value: 102000,
        currency: "PLN",
        uncertain: true,
        uncertain_reasons: ["Nie znaleziono jednoznacznej daty końca"],
        fields_confidence: {},
        source: "claude",
      },
    } as never);

    renderDialog();
    addPdf();
    fireEvent.click(extractBtn());

    await waitFor(() => expect(extractOrderPdf).toHaveBeenCalledOnce());
    expect(extractOrderPdf).toHaveBeenCalledWith(10, expect.any(File), 7);

    await waitFor(() =>
      expect(screen.getByDisplayValue("PO-123")).toBeInTheDocument(),
    );
    expect(screen.getByDisplayValue("2026-06-01")).toBeInTheDocument();
    expect(screen.getByDisplayValue("2026-12-31")).toBeInTheDocument();
    // Admin: kwota zastosowana.
    expect(screen.getByDisplayValue("17000")).toBeInTheDocument();

    expect(screen.getByText("Sprawdź dane!")).toBeInTheDocument();
    expect(
      screen.getByText(/Nie znaleziono jednoznacznej daty końca/),
    ).toBeInTheDocument();
  });

  it("brak banera gdy odczyt jest pewny (uncertain=false)", async () => {
    act(() => {
      useAuthStore.setState({ user: user("admin"), hydrated: true });
    });
    extractOrderPdf.mockResolvedValue({
      data: {
        title: "PO-9",
        start_date: "2026-01-01",
        end_date: null,
        rate_client: 15000,
        rate_unit: "month",
        total_value: null,
        currency: "PLN",
        uncertain: false,
        uncertain_reasons: [],
        fields_confidence: {},
        source: "claude",
      },
    } as never);

    renderDialog();
    addPdf();
    fireEvent.click(extractBtn());

    await waitFor(() =>
      expect(screen.getByDisplayValue("PO-9")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Sprawdź dane!")).not.toBeInTheDocument();
  });

  it("Delivery Lead: odczyt wypełnia pola operacyjne, kwoty pozostają ukryte", async () => {
    act(() => {
      useAuthStore.setState({ user: user("delivery_lead"), hydrated: true });
    });
    extractOrderPdf.mockResolvedValue({
      data: {
        title: "PO-DL",
        start_date: "2026-03-01",
        end_date: "2026-09-30",
        // Backend redaguje kwoty dla ról bez VIEW_FINANCE.
        rate_client: null,
        rate_unit: null,
        total_value: null,
        currency: null,
        uncertain: false,
        uncertain_reasons: [],
        fields_confidence: {},
        source: "claude",
      },
    } as never);

    renderDialog();
    addPdf();
    fireEvent.click(extractBtn());

    await waitFor(() =>
      expect(screen.getByDisplayValue("PO-DL")).toBeInTheDocument(),
    );
    expect(screen.getByDisplayValue("2026-03-01")).toBeInTheDocument();
    // Finanse dalej ukryte — extraction nie może ich przemycić.
    expect(screen.queryByText(/Stawka przychodowa/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Total value/)).not.toBeInTheDocument();
  });

  it("wykrywa MD z pozycji, przelicza koszt i wysyła snapshot jednostki/waluty", async () => {
    const userActions = userEvent.setup();
    act(() => {
      useAuthStore.setState({ user: user("admin"), hydrated: true });
    });
    const hourlyContract: ContractWithOrdersRead = {
      ...contract,
      rate_candidate: 125,
      rate_unit: "hourly",
      rate_client_currency: "EUR",
      rate_candidate_currency: "GBP",
      latest_order_rate_client: 150,
    };
    extractOrderPdf.mockResolvedValue({
      data: {
        title: "PO-MD",
        start_date: "2026-09-01",
        end_date: "2026-12-31",
        rate_client: 1320,
        rate_unit: "md",
        total_value: null,
        currency: "USD",
        md_total: null,
        uncertain: false,
        uncertain_reasons: [],
        fields_confidence: {},
        source: "claude",
      },
    } as never);

    renderDialog(hourlyContract);
    const file = addPdf();
    fireEvent.click(extractBtn());

    await waitFor(() =>
      expect(extractOrderPdf).toHaveBeenCalledWith(10, file, 7),
    );
    expect(screen.getByLabelText(/Stawka kosztowa/)).toHaveValue("1000");
    expect(screen.getByLabelText(/Stawka przychodowa/)).toHaveValue("1320");
    expect(screen.getByRole("radio", { name: "MD" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(
      screen.getByText(
        "Jednostkę stawki zmieniono na MD na podstawie odczytanej pozycji",
      ),
    ).toHaveAttribute("role", "status");
    expect(
      screen.getByRole("combobox", {
        name: "Waluta zamówienia (przychodowa)",
      }),
    ).toHaveValue("USD");
    expect(
      screen.getByRole("combobox", { name: "Waluta stawki kosztowej" }),
    ).toHaveValue("GBP");
    expect(
      screen.getByText(/Marża zostanie pokazana po niezależnym przeliczeniu/),
    ).toBeInTheDocument();

    await userActions.click(
      screen.getByRole("button", { name: "Zapisz przedłużenie" }),
    );
    await waitFor(() => expect(createOrderExtension).toHaveBeenCalledOnce());
    const sent = createOrderExtension.mock.calls[0][1];
    expect(sent.get("rate_candidate")).toBe("1000");
    expect(sent.get("rate_client")).toBe("1320");
    expect(sent.get("rate_unit")).toBe("daily");
    expect(sent.get("rate_client_currency")).toBe("USD");
    expect(sent.get("rate_candidate_currency")).toBe("GBP");
    expect(sent.has("currency")).toBe(false);
  });
});

// ── Bank Pocztowy: stawka MD → godzinowa + „Sprawdź numer zamówienia" ────────

describe("ExtendOrderDialog — polityka Banku Pocztowego", () => {
  beforeEach(() => {
    createOrderExtension.mockReset();
    createOrderExtension.mockResolvedValue({ data: {} } as never);
    extractOrderPdf.mockReset();
    act(() => {
      useAuthStore.setState({ user: user("admin"), hydrated: true });
    });
  });

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, hydrated: true });
    });
  });

  it("pokazuje OBA: oryginał MD z dokumentu i przeliczoną stawkę godzinową (edytowalną)", async () => {
    extractOrderPdf.mockResolvedValue({
      data: {
        title: "BP/DIT/2026/0451",
        start_date: "2026-09-01",
        end_date: "2026-12-31",
        // Backend (polityka BP) zwraca stawkę już przeliczoną na zł/h…
        rate_client: 200,
        rate_unit: "hour",
        // …a oryginał za 1 MD jedzie obok do pokazania.
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

    // Pole stawki dostało wartość godzinową, helper pokazuje oryginał MD.
    await waitFor(() =>
      expect(screen.getByDisplayValue("200")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Z dokumentu: 1600 PLN\/MD/)).toBeInTheDocument();

    // Czysty odczyt BP → zero banera „Sprawdź dane!" (wymóg ticketu).
    expect(screen.queryByText("Sprawdź dane!")).not.toBeInTheDocument();

    // Przeliczona stawka jest zwykłym polem — użytkownik może ją poprawić
    // przed zapisem (na wypadek błędu odczytu z PDF).
    const rateInput = screen.getByDisplayValue("200");
    fireEvent.change(rateInput, { target: { value: "210" } });
    expect(screen.getByDisplayValue("210")).toBeInTheDocument();
    expect(screen.getByText(/Z dokumentu: 1600 PLN\/MD/)).toBeInTheDocument();
  });

  it("brak numeru w dokumencie → Sprawdź numer zamówienia przy polu, znika po wpisaniu", async () => {
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
    // Pole numeru pozostało puste — polityka nie zgaduje.
    expect(screen.getByLabelText(/Numer zamówienia/)).toHaveValue("");

    // Ręczne wpisanie numeru unieważnia komunikat.
    fireEvent.change(screen.getByLabelText(/Numer zamówienia/), {
      target: { value: "BP/2026/77" },
    });
    expect(
      screen.queryByText("Sprawdź numer zamówienia"),
    ).not.toBeInTheDocument();
  });

  it("nowy plik kasuje komunikat numeru i helper stawki z poprzedniego odczytu", async () => {
    extractOrderPdf.mockResolvedValue({
      data: {
        title: null,
        start_date: null,
        end_date: null,
        rate_client: 200,
        rate_client_gross: 246,
        rate_unit: "hour",
        rate_client_md: 1600,
        total_value: null,
        currency: null,
        md_total: null,
        uncertain: true,
        uncertain_reasons: ["Nie znaleziono dat okresu zamówienia (od–do)"],
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
    expect(screen.getByText(/Z dokumentu: 1600 PLN\/MD/)).toBeInTheDocument();
    expect(screen.getByText(/246 PLN\/h brutto.*200 PLN\/h netto/)).toBeInTheDocument();

    // Wybór innego pliku — stany odczytu wracają do zera (dotyczyły innego PDF).
    addPdf("inne-zamowienie.pdf");
    expect(
      screen.queryByText("Sprawdź numer zamówienia"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Z dokumentu:/)).not.toBeInTheDocument();
  });
});
