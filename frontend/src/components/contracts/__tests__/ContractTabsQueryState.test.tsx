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
      expect(keys).toContainEqual(["contracts-quick-counts"]);
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

  // Aneksy podpisane w Generatorze aneksów zapisują cztery typy spoza
  // pierwotnej czwórki — do 13.10.2026 ich wiersz nie miał nazwy typu.
  it("aneks z Generatora aneksów ma nazwę typu, a nieznany typ — „Aneks”", async () => {
    const amendment = (id: number, amendment_type: string, new_values: object) => ({
      id,
      contract_id: 5,
      amendment_type,
      old_values: {},
      new_values,
      effective_date: "2026-11-16",
      reason: null,
      document_id: null,
      created_by: null,
      created_by_email: null,
      created_at: "2026-10-10T10:00:00Z",
    });
    mocks.get.mockResolvedValue({
      data: [
        amendment(1, "start_date_change", { start_date: "2026-11-16" }),
        amendment(2, "party_data_change", { legal_name: "ZAJĄC IT Piotr Zając" }),
        amendment(3, "subcontractor_consent", { delegate_name: "Paweł Sowa" }),
        amendment(4, "mandate_change", { rate_changed: true }),
        amendment(5, "typ_z_przyszlosci", {}),
      ],
    });
    renderWith(<ContractAmendmentsTab contractId={5} clientId={2} readOnly />);

    expect(await screen.findByText("Zmiana daty startu")).toBeInTheDocument();
    expect(screen.getByText("Uzupełnienie danych firmy")).toBeInTheDocument();
    // Nazwa typu i etykieta pola `delegate_name` brzmią tak samo.
    expect(screen.getAllByText("Osoba skierowana").length).toBeGreaterThan(0);
    expect(screen.getByText("Aneks do umowy zlecenie")).toBeInTheDocument();
    expect(screen.getByText("Aneks")).toBeInTheDocument();
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
});

// Zakładka „Faktury” od 19.11.2026: faktury konsultanta z KSeF z Rozliczeń,
// tylko do odczytu (decyzja Artura). Ręczny rejestr `/api/invoices` z „Dodaj
// fakturę” zniknął — na produkcji nie miał ani jednego wiersza.
describe("ContractInvoicesTab — faktury konsultanta z KSeF", () => {
  const PAYLOAD = {
    contract_id: 5,
    client_id: 12,
    invoices: [
      {
        id: 2,
        ksef_number: "9970000001-20261117-AAAAAAAAAAAA-AB",
        invoice_number: "FK 2/11/2026",
        invoice_type: "Kor",
        is_correction: true,
        issue_date: "2026-11-17",
        period_month: "2026-10",
        nip_state: "known",
        net_amount: "-1500.00",
        gross_amount: "-1845.00",
        currency: "PLN",
      },
      {
        id: 1,
        ksef_number: "9970000001-20261003-BBBBBBBBBBBB-AB",
        invoice_number: "FV 9/10/2026",
        invoice_type: "Vat",
        is_correction: false,
        issue_date: "2026-10-03",
        period_month: "2026-09",
        nip_state: "suggested",
        net_amount: "18000.00",
        gross_amount: "22140.00",
        currency: "PLN",
      },
    ],
  };

  it("czyta faktury z KSeF kontraktu i linkuje miesiąc do Rozliczeń, bez „Dodaj fakturę”", async () => {
    mocks.get.mockResolvedValue({ data: PAYLOAD });
    renderWith(<ContractInvoicesTab contractId={5} />);

    // Tytuł sekcji stoi już w stanie ładowania — czekamy na wiersz z danymi.
    expect(await screen.findByText("Korekta")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Faktury konsultanta z KSeF" }),
    ).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/contracts/5/contractor-invoices");
    expect(screen.getByText("Faktura")).toBeInTheDocument();
    expect(screen.getByText("FK 2/11/2026")).toBeInTheDocument();
    expect(screen.getByText("9970000001-20261117-AAAAAAAAAAAA-AB")).toBeInTheDocument();
    expect(screen.getByText("do zatwierdzenia")).toBeInTheDocument();

    const october = screen.getByRole("link", { name: "10.2026" });
    expect(october).toHaveAttribute(
      "href",
      "/finance?view=settlements&stClient=12&stMonth=2026-10&stContract=5",
    );
    expect(
      screen.getByRole("link", { name: /Otwórz 10\.2026 w Rozliczeniach/ }),
    ).toHaveAttribute("href", october.getAttribute("href"));

    expect(screen.queryByRole("button", { name: /Dodaj fakturę/ })).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("pusty stan dopiero po udanym odczycie", async () => {
    mocks.get.mockResolvedValue({ data: { ...PAYLOAD, invoices: [] } });
    renderWith(<ContractInvoicesTab contractId={5} />);

    expect(
      await screen.findByText("Brak faktur konsultanta w KSeF dla tego kontraktu."),
    ).toBeInTheDocument();
  });

  it("awaria odczytu nie udaje braku faktur i daje się ponowić", async () => {
    mocks.get.mockRejectedValueOnce(httpError(500));
    renderWith(<ContractInvoicesTab contractId={5} />);

    expect(await screen.findByText(FAILURE)).toBeInTheDocument();
    expect(
      screen.queryByText("Brak faktur konsultanta w KSeF dla tego kontraktu."),
    ).not.toBeInTheDocument();

    mocks.get.mockResolvedValueOnce({ data: PAYLOAD });
    fireEvent.click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    expect(await screen.findByText("Korekta")).toBeInTheDocument();
  });

  it("wyłączony moduł rozliczeń: komunikat z API zamiast pustej listy", async () => {
    mocks.get.mockRejectedValue(httpError(404, "Moduł rozliczeń klientów jest wyłączony."));
    renderWith(<ContractInvoicesTab contractId={5} />);

    expect(
      await screen.findByText("Moduł rozliczeń klientów jest wyłączony."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Brak faktur konsultanta w KSeF dla tego kontraktu."),
    ).not.toBeInTheDocument();
  });
});
