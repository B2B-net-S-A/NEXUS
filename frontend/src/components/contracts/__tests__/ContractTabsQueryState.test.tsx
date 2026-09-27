/**
 * Zakładki kontraktu (aneksy, onboarding, sprzęt, notatki) — audyt FE-02..07.
 *
 * * awaria odczytu NIE może renderować się jak pusta lista (FE-03) — pusta
 *   lista onboardingu zaprasza do „wygenerowania”, czyli do zdublowania
 *   listy, która może już istnieć;
 * * domyślna lista onboardingu to JEDNO żądanie z blokadą przycisku (FE-04);
 * * nieudane mutacje mówią o tym toastem (FE-05);
 * * aneks odświeża listę kontraktów i historię stawek (FE-02).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  equipmentList: vi.fn(),
  equipmentUpdate: vi.fn(),
  notesTimeline: vi.fn(),
  createNote: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    patch: (...a: unknown[]) => mocks.patch(...a),
    delete: (...a: unknown[]) => mocks.del(...a),
  },
  contractEquipmentApi: {
    list: (...a: unknown[]) => mocks.equipmentList(...a),
    create: vi.fn(),
    update: (...a: unknown[]) => mocks.equipmentUpdate(...a),
    delete: vi.fn(),
  },
  contractsApi: {
    notesTimeline: (...a: unknown[]) => mocks.notesTimeline(...a),
    createNote: (...a: unknown[]) => mocks.createNote(...a),
  },
  // Słowniki czytane przez `contract-timeline-labels.ts` (lista zmian aneksu).
  CONTRACT_FIELD_LABELS: { rate_candidate: "Stawka kandydata" },
  CONTRACT_TERMINATION_REASONS: [],
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showToast: mocks.showToast,
    showError: (message: string) => mocks.showToast(message, "error"),
  }),
}));

vi.mock("@/components/RequireRole", () => ({
  RequireRole: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/store/auth", async () => {
  const actual =
    await vi.importActual<typeof import("@/store/auth")>("@/store/auth");
  const state = { user: { id: 1, role: "admin", roles: ["admin"] } };
  return {
    ...actual,
    useAuthStore: (selector: (s: typeof state) => unknown) => selector(state),
    canManageCandidateFinance: () => true,
    canViewClientFinance: () => true,
  };
});

import { ContractOnboardingTab } from "@/components/ContractOnboardingTab";
import { ContractAmendmentsTab } from "@/components/ContractAmendmentsTab";
import { ContractEquipmentTab } from "@/components/contracts/ContractEquipmentTab";
import { ContractNotesTab } from "@/components/contracts/ContractNotesTab";
import { ContractInvoicesTab } from "@/components/ContractInvoicesTab";

function httpError(status: number, detail?: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: { status, data: detail ? { detail } : {} },
  });
}

function renderWith(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return { client, invalidate };
}

const SEED = /Wygeneruj domyślny checklist/;
const FAILURE = "Nie udało się pobrać danych";

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
});

describe("ContractOnboardingTab", () => {
  it("awaria odczytu pokazuje błąd z ponowieniem i CHOWA generowanie listy", async () => {
    mocks.get.mockRejectedValueOnce(httpError(500));
    renderWith(<ContractOnboardingTab contractId={7} />);

    expect(await screen.findByText(FAILURE)).toBeInTheDocument();
    expect(screen.queryByText(SEED)).not.toBeInTheDocument();
    expect(screen.queryByText("Brak listy onboardingowej.")).not.toBeInTheDocument();

    mocks.get.mockResolvedValueOnce({ data: [] });
    fireEvent.click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    expect(await screen.findByText(SEED)).toBeInTheDocument();
  });

  it("generowanie domyślnej listy to JEDNO żądanie, a przycisk blokuje się w trakcie", async () => {
    mocks.get.mockResolvedValue({ data: [] });
    let resolveSeed: (value: unknown) => void = () => {};
    mocks.post.mockReturnValue(
      new Promise((resolve) => {
        resolveSeed = resolve;
      }),
    );
    renderWith(<ContractOnboardingTab contractId={7} />);

    const button = await screen.findByRole("button", { name: SEED });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(button).toBeDisabled());
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(mocks.post).toHaveBeenCalledWith("/api/contracts/7/onboarding/seed");
    resolveSeed({ data: [] });
  });

  it("nieudane generowanie mówi o tym toastem z komunikatem serwera", async () => {
    mocks.get.mockResolvedValue({ data: [] });
    mocks.post.mockRejectedValue(httpError(403, "Brak uprawnień do kontraktu"));
    renderWith(<ContractOnboardingTab contractId={7} />);

    fireEvent.click(await screen.findByRole("button", { name: SEED }));
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        "Brak uprawnień do kontraktu",
        "error",
      ),
    );
  });
});

describe("ContractAmendmentsTab", () => {
  it("awaria odczytu nie udaje „Brak aneksów”", async () => {
    mocks.get.mockRejectedValue(httpError(500));
    renderWith(<ContractAmendmentsTab contractId={5} clientId={2} />);

    expect(await screen.findByText(FAILURE)).toBeInTheDocument();
    expect(screen.queryByText(/Brak aneksów/)).not.toBeInTheDocument();
  });

  it("zapis aneksu odświeża listę kontraktów, kończące się i historię stawek", async () => {
    mocks.get.mockResolvedValue({ data: [] });
    mocks.post.mockResolvedValue({ data: {} });
    const { invalidate } = renderWith(
      <ContractAmendmentsTab contractId={5} clientId={2} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /Zmień zakres/ }));
    fireEvent.click(screen.getByRole("button", { name: /Zapisz aneks/ }));

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      const keys = invalidate.mock.calls.map((call) => call[0]?.queryKey);
      expect(keys).toContainEqual(["contracts-v2"]);
      expect(keys).toContainEqual(["contracts-expiring-v2"]);
      expect(keys).toContainEqual(["contract-rate-history", 5]);
    });
  });
});

describe("ContractEquipmentTab", () => {
  it("awaria odczytu pokazuje błąd, nie „Brak pozycji”", async () => {
    mocks.equipmentList.mockRejectedValue(httpError(500));
    renderWith(<ContractEquipmentTab contractId={9} />);

    expect(await screen.findByText(FAILURE)).toBeInTheDocument();
    expect(screen.queryByText(/Brak pozycji/)).not.toBeInTheDocument();
  });

  it("nieudany zwrot sprzętu kończy się toastem", async () => {
    mocks.equipmentList.mockResolvedValue({
      data: [
        {
          id: 1,
          contract_id: 9,
          item_type: "laptop",
          owner: "ours",
          brand_model: "X1",
          serial_number: null,
          return_due_date: null,
          return_status: "pending",
        },
      ],
    });
    mocks.equipmentUpdate.mockRejectedValue(httpError(500));
    renderWith(<ContractEquipmentTab contractId={9} />);

    fireEvent.click(await screen.findByRole("button", { name: /Zwrócono/ }));
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        "Nie udało się zapisać zmiany sprzętu.",
        "error",
      ),
    );
    const payload = mocks.equipmentUpdate.mock.calls[0][2] as {
      returned_date: string;
    };
    expect(payload.returned_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe("ContractNotesTab", () => {
  it("awaria odczytu pokazuje błąd z ponowieniem zamiast zachęty do powiązania", async () => {
    mocks.notesTimeline.mockRejectedValueOnce(httpError(500));
    renderWith(<ContractNotesTab contractId={4} />);

    expect(await screen.findByText(FAILURE)).toBeInTheDocument();
    expect(screen.queryByText(/Brak notatek/)).not.toBeInTheDocument();

    mocks.notesTimeline.mockResolvedValueOnce({ data: [] });
    fireEvent.click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    expect(await screen.findByText(/Brak notatek/)).toBeInTheDocument();
  });

  it("pusta zakładka nie każe ustawiać pola technicznego (runda 10, F03)", async () => {
    mocks.notesTimeline.mockResolvedValueOnce({ data: [] });
    renderWith(<ContractNotesTab contractId={4} />);
    expect(await screen.findByText(/Brak notatek/)).toBeInTheDocument();
    expect(screen.queryByText(/contract_id/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj notatkę/ })).toBeNull();
  });

  it("notatkę dodaje się wprost przy kontrakcie (runda 10, F03)", async () => {
    mocks.notesTimeline.mockResolvedValue({ data: [] });
    mocks.createNote.mockResolvedValueOnce({ data: { id: 1 } });
    renderWith(<ContractNotesTab contractId={4} canAddNote />);

    const button = await screen.findByRole("button", { name: /Dodaj notatkę/ });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Nowa notatka przy kontrakcie/), {
      target: { value: "  Ustalenia z rozmowy  " },
    });
    fireEvent.change(screen.getByLabelText("Rodzaj notatki"), {
      target: { value: "call" },
    });
    fireEvent.click(button);
    await waitFor(() =>
      expect(mocks.createNote).toHaveBeenCalledWith(4, {
        content: "Ustalenia z rozmowy",
        note_type: "call",
      }),
    );
    await waitFor(() => expect(mocks.notesTimeline).toHaveBeenCalledTimes(2));
  });
});

describe("audyt 24.09 (blok D) — zakładki kontraktu", () => {
  it("aneks pokazuje zmienione pola po polsku, nie surowy JSON (N9)", async () => {
    mocks.get.mockResolvedValue({
      data: [
        {
          id: 1,
          contract_id: 5,
          amendment_type: "extension",
          old_values: { end_date: "2026-06-30", status: "ending" },
          new_values: { end_date: "2026-09-30", status: "active" },
          effective_date: "2026-06-15",
          reason: null,
          document_id: null,
          created_by: null,
          created_by_email: null,
          created_at: "2026-06-15T10:00:00Z",
        },
      ],
    });
    renderWith(<ContractAmendmentsTab contractId={5} clientId={2} readOnly />);

    expect(await screen.findByText(/→ 30\.09\.2026/)).toBeInTheDocument();
    expect(screen.getByText(/→ Aktywny/)).toBeInTheDocument();
    expect(screen.queryByText(/"end_date"/)).not.toBeInTheDocument();
  });

  it("formularz aneksu nie ma już gałęzi „wcześniejsze zakończenie” (S5)", async () => {
    mocks.get.mockResolvedValue({ data: [] });
    renderWith(<ContractAmendmentsTab contractId={5} clientId={2} />);
    fireEvent.click(await screen.findByRole("button", { name: /Zmień zakres/ }));
    expect(screen.queryByText("Data faktycznego zakończenia")).not.toBeInTheDocument();
  });

  it("usunięcie sprzętu pyta w wierszu, nie natywnym oknem (N7)", async () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    mocks.equipmentList.mockResolvedValue({
      data: [
        {
          id: 3,
          contract_id: 9,
          item_type: "laptop",
          owner: "ours",
          brand_model: "X1",
          serial_number: null,
          return_due_date: null,
          return_status: "returned",
        },
      ],
    });
    renderWith(<ContractEquipmentTab contractId={9} />);

    fireEvent.click(await screen.findByRole("button", { name: /Usuń pozycję/ }));
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Potwierdź usunięcie/ })).toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("faktury: status po polsku, a odmowa usunięcia kończy się toastem (N9, N10)", async () => {
    mocks.get.mockResolvedValue({
      data: [
        {
          id: 7,
          contract_id: 5,
          direction: "to_client",
          invoice_number: "FV/1",
          period_month: null,
          period_year: null,
          issue_date: "2026-09-01",
          due_date: "2026-09-15",
          paid_date: "2026-09-10",
          amount: 1000,
          currency: "PLN",
          status: "paid",
          notes: null,
        },
      ],
    });
    mocks.del.mockRejectedValue(httpError(403, "Brak uprawnień do faktur"));
    renderWith(<ContractInvoicesTab contractId={5} />);

    expect(await screen.findByText("Zapłacona")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Usuń fakturę FV/1" }));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź usunięcie faktury FV/1" }));
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        "Brak uprawnień do faktur",
        "error",
      ),
    );
  });
});

// Runda 10 (R10-X1-1): puste pole kwoty zapisywało fakturę na 0 zł, a grosze
// były blokowane domyślnym `step=1`.
describe("ContractInvoicesTab — kwota faktury", () => {
  async function openForm() {
    mocks.get.mockResolvedValue({ data: [] });
    renderWith(<ContractInvoicesTab contractId={5} />);
    fireEvent.click(await screen.findByRole("button", { name: /Dodaj fakturę/ }));
    const field = (label: string) =>
      screen.getByText(label).parentElement!.querySelector("input")!;
    const form = screen.getByRole("button", { name: "Zapisz" }).closest("form")!;
    return { input: field("Kwota"), number: field("Numer"), form };
  }

  it("pola kwoty i numeru są wymagane, kwota przyjmuje grosze", async () => {
    const { input, number } = await openForm();
    expect(input).toHaveAttribute("step", "0.01");
    expect(input).toBeRequired();
    expect(number).toBeRequired();
  });

  it("UI F01: pusty formularz nie wysyła faktury (najpierw numer)", async () => {
    const { form } = await openForm();
    fireEvent.submit(form);
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.showToast).toHaveBeenCalledWith("Podaj numer faktury.", "error");
  });

  it("zerowa albo ujemna kwota nie wysyła faktury", async () => {
    const { input, number, form } = await openForm();
    fireEvent.change(number, { target: { value: "FV/9" } });
    for (const value of ["", "0", "-5"]) {
      fireEvent.change(input, { target: { value } });
      fireEvent.submit(form);
    }
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.showToast).toHaveBeenCalledWith(
      "Podaj kwotę faktury większą od zera.",
      "error",
    );
  });

  it("kwota z groszami idzie do API bez zaokrąglenia", async () => {
    mocks.post.mockResolvedValue({ data: {} });
    const { input, number, form } = await openForm();
    fireEvent.change(number, { target: { value: " FV/2026/09/1 " } });
    // UI F13: 123,45 PLN.
    fireEvent.change(input, { target: { value: "123.45" } });
    fireEvent.submit(form);
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    expect(mocks.post.mock.calls[0][1]).toMatchObject({
      amount: 123.45,
      invoice_number: "FV/2026/09/1",
    });
  });
});
