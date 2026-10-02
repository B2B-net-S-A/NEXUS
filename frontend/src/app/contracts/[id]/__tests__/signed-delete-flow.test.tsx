import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  role: "admin",
  push: vi.fn(),
  apiGet: vi.fn(),
  getContract: vi.fn(),
  getDocuments: vi.fn(),
  deleteContract: vi.fn(),
  forceDeleteSigned: vi.fn(),
  updateContract: vi.fn(),
  activities: vi.fn(),
  impersonating: false,
  search: "",
  replace: vi.fn(),
  updateStatus: vi.fn(),
  // Flagi, które strona dostaje z `lib/contract-access.ts` — nadpisania
  // względem kompletu „wolno wszystko” (patrz mock niżej).
  access: {} as Record<string, boolean>,
  accessCalls: [] as Array<{
    impersonating: boolean;
    clientId: number | null | undefined;
  }>,
  amendmentsTabProps: null as null | {
    readOnly?: boolean;
    onRequestTermination?: () => void;
  },
}));

// O tym, KTO co może, rozstrzyga `lib/contract-access.ts` (uprawnienia konta;
// ma własne testy). Ten plik sprawdza, co strona robi z gotowymi flagami —
// dlatego bramka jest tu podstawiona, a nie odtwarzana z ról.
vi.mock("@/lib/contract-access", () => {
  const everything = {
    isAdmin: true,
    canManageFinance: false,
    canViewBenchmark: true,
    canViewInvoices: true,
    canManageInvoices: true,
    canEditContract: true,
    financeAmountsOnly: false,
    canEditContractStatus: true,
    canRecoverTermination: true,
    canViewFinance: true,
    canViewContractDocuments: true,
    canEditContractDocuments: true,
    canReassignClient: true,
  };
  return {
    contractAccess: (
      _user: unknown,
      options: { impersonating: boolean; clientId: number | null | undefined },
    ) => {
      mocks.accessCalls.push(options);
      return { ...everything, ...mocks.access };
    },
  };
});

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "563" }),
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams(mocks.search),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn(), showToast: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/store/auth", async () => {
  const actual =
    await vi.importActual<typeof import("@/store/auth")>("@/store/auth");
  return {
    ...actual,
    useAuthStore: (
      selector: (state: {
        user: { role: string; roles: string[] };
        realUser: { role: string; roles: string[] } | null;
        hydrated: boolean;
      }) => unknown,
    ) =>
      selector({
        user: { role: mocks.role, roles: [mocks.role] },
        realUser: mocks.impersonating
          ? { role: "admin", roles: ["admin"] }
          : null,
        hydrated: true,
      }),
  };
});

vi.mock("@/components/ds/AppModal", () => ({
  AppModal: ({
    open,
    title,
    description,
    footer,
    children,
  }: {
    open: boolean;
    title: string;
    description?: string;
    footer?: React.ReactNode;
    children: React.ReactNode;
  }) =>
    open ? (
      <section role="dialog" aria-label={title}>
        <h2>{title}</h2>
        {description ? <p>{description}</p> : null}
        {children}
        {footer}
      </section>
    ) : null,
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  // Słowniki etykiet czytane przez `contract-timeline-labels.ts` (UAT B23);
  // mock modułu w całości musi je wystawić, inaczej import strony pada.
  CONTRACT_FIELD_LABELS: {},
  contractsApi: {
    get: (...args: unknown[]) => mocks.getContract(...args),
    documents: (...args: unknown[]) => mocks.getDocuments(...args),
    activities: (...args: unknown[]) => mocks.activities(...args),
    rateHistory: vi.fn(),
    update: (...args: unknown[]) => mocks.updateContract(...args),
    updateStatus: (...args: unknown[]) => mocks.updateStatus(...args),
    delete: (...args: unknown[]) => mocks.deleteContract(...args),
    forceDeleteSigned: (...args: unknown[]) =>
      mocks.forceDeleteSigned(...args),
  },
  extractErrorMsg: () => "Nie udało się usunąć kontraktu.",
  CONTRACT_TERMINATION_REASONS: [],
}));

vi.mock("@/components/contracts/AddProjectDialog", () => ({
  AddProjectDialog: () => null,
}));
vi.mock("@/components/ContractAmendmentsTab", () => ({
  ContractAmendmentsTab: (props: {
    readOnly?: boolean;
    onRequestTermination?: () => void;
  }) => {
    mocks.amendmentsTabProps = props;
    return <p>zakładka aneksów</p>;
  },
}));
vi.mock("@/components/ContractDocumentsTab", () => ({
  ContractDocumentsTab: () => null,
  summariseComplianceRisk: () => ({ risk: "none" }),
}));
vi.mock("@/components/ContractEquipmentTab", () => ({
  ContractEquipmentTab: () => null,
}));
vi.mock("@/components/ContractInvoicesTab", () => ({
  ContractInvoicesTab: () => null,
}));
vi.mock("@/components/ContractOnboardingTab", () => ({
  ContractOnboardingTab: () => null,
}));
vi.mock("@/components/contracts/ContractNotesTab", () => ({
  ContractNotesTab: () => null,
}));
vi.mock("@/components/contracts/ContractRateBenchmarkCard", () => ({
  ContractRateBenchmarkCard: () => <p>karta benchmarku</p>,
}));
vi.mock("@/components/contracts/ContractTerminationDialog", () => ({
  ContractTerminationDialog: () => null,
}));
vi.mock("@/components/contracts/FinancialRatesCard", () => ({
  FinancialRatesCard: () => null,
}));

import ContractDetailPage from "../page";

const RETURN_TO =
  "/contracts?status=draft&contract_type=b2b&q=Agnieszka&page=3";

const contract = {
  id: 563,
  candidate_id: 77,
  client_id: 42,
  job_id: null,
  candidate_name: "Agnieszka Urbaniak",
  client_name: "Nordea",
  job_title: null,
  start_date: "2026-01-01",
  end_date: null,
  client_order_end_date: null,
  rate_candidate: null,
  rate_client: null,
  candidate_rate_schedule: [],
  client_rate_schedule: [],
  framework_rate_schedule: [],
  framework_rate: null,
  target_rate_min: null,
  target_rate_max: null,
  currency: "PLN",
  rate_client_currency: "EUR",
  rate_candidate_currency: "PLN",
  eur_pln_rate: null,
  rate_unit: "daily",
  billing_hours_per_month: 160,
  margin: null,
  contract_type: "b2b",
  status: "active",
  documents: null,
  client_pm_name: null,
  client_pm_email: null,
  line_manager: null,
  work_mode: null,
  office_location: null,
  team_name: null,
  project_name: null,
  handover_notes: null,
  order_consumption: null,
  order_consumption_unit: null,
  termination_reason: null,
  termination_lessons: null,
  terminated_at: null,
  monthly_rate_candidate: null,
  monthly_rate_client: null,
  monthly_margin: null,
  created_at: "2026-01-01T12:00:00Z",
  updated_at: "2026-01-01T12:00:00Z",
  related_contracts: [],
};

const signedContractConflict = {
  response: {
    status: 409,
    data: {
      detail: {
        code: "contract_has_signed_generated_contract",
        requires_admin_confirmation: true,
        contractor_name: "Agnieszka Urbaniak",
      },
    },
  },
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ContractDetailPage />
    </QueryClientProvider>,
  );
}

async function requestDelete() {
  const user = userEvent.setup({ delay: null });
  renderPage();

  await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
  await user.click(screen.getByRole("button", { name: /^Usuń$/ }));

  const firstDialog = screen.getByRole("dialog", {
    name: "Usunąć kontrakt?",
  });
  await user.click(
    within(firstDialog).getByRole("button", { name: "Usuń kontrakt" }),
  );

  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.role = "admin";
  mocks.access = {};
  mocks.accessCalls = [];
  mocks.amendmentsTabProps = null;
  mocks.impersonating = false;
  mocks.search = "";
  window.history.replaceState(
    {},
    "",
    `/contracts/563?from=contracts&returnTo=${encodeURIComponent(RETURN_TO)}`,
  );
  mocks.apiGet.mockResolvedValue({ data: [] });
  mocks.getContract.mockResolvedValue({ data: contract });
  mocks.getDocuments.mockResolvedValue({ data: [] });
  mocks.deleteContract.mockRejectedValue(signedContractConflict);
  mocks.forceDeleteSigned.mockResolvedValue({ data: null });
  mocks.updateContract.mockResolvedValue({ data: contract });
});

describe("ContractDetailPage — edycja walut stawek", () => {
  it("prefilluje i zapisuje niezależną walutę klienta oraz kandydata", async () => {
    mocks.access = { canManageFinance: true };
    const user = userEvent.setup({ delay: null });
    renderPage();

    await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
    // Kotwice są tu load-bearing (jak w `/^Usuń$/` niżej): karta kontraktu ma
    // też ołówki edycji w miejscu z etykietami „Edytuj: E-mail" / „Edytuj:
    // Telefon", więc gołe `/Edytuj/` trafia w kilka przycisków i `getByRole`
    // wywala się na „Found multiple elements". Chodzi o przycisk edycji CAŁEJ
    // karty, nie o pojedyncze pole.
    await user.click(screen.getByRole("button", { name: /^Edytuj$/ }));

    const clientCurrency = screen.getByRole("combobox", {
      name: "Waluta stawki przychodowej (klienta)",
    });
    const candidateCurrency = screen.getByRole("combobox", {
      name: "Waluta stawki kosztowej (kandydata / umowy ramowej)",
    });
    expect(clientCurrency).toHaveValue("EUR");
    expect(candidateCurrency).toHaveValue("PLN");

    await user.selectOptions(clientCurrency, "GBP");
    await user.selectOptions(candidateCurrency, "EUR");
    await user.click(screen.getByRole("button", { name: /Zapisz/ }));

    await waitFor(() => expect(mocks.updateContract).toHaveBeenCalledTimes(1));
    expect(mocks.updateContract).toHaveBeenCalledWith(
      563,
      expect.objectContaining({
        rate_client_currency: "GBP",
        rate_candidate_currency: "EUR",
      }),
    );
    expect(mocks.updateContract.mock.calls[0]?.[1]).not.toHaveProperty("currency");
  });
});

describe("ContractDetailPage — sama zmiana kwot edytuje tylko kwoty (audyt 22.09)", () => {
  it("konto ze zmianą kwot bez edycji kontraktów dostaje „Edytuj stawki” i wysyła wyłącznie pola kwot", async () => {
    mocks.access = {
      isAdmin: false,
      canEditContract: false,
      canEditContractStatus: false,
      canReassignClient: false,
      canManageFinance: true,
      financeAmountsOnly: true,
    };
    const user = userEvent.setup({ delay: null });
    renderPage();

    await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
    // Bez edycji kontraktów nie ma pełnej edycji ani usuwania.
    expect(screen.queryByRole("button", { name: /^Edytuj$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Usuń$/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Edytuj stawki$/ }));
    expect(screen.getByText("Edycja stawek")).toBeInTheDocument();
    // Pola operacyjne (daty, status, zużycie) są schowane.
    expect(screen.queryByLabelText("Data rozpoczęcia")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Status")).not.toBeInTheDocument();

    await user.selectOptions(
      screen.getByRole("combobox", {
        name: "Waluta stawki przychodowej (klienta)",
      }),
      "GBP",
    );
    await user.click(screen.getByRole("button", { name: /Zapisz/ }));

    await waitFor(() => expect(mocks.updateContract).toHaveBeenCalledTimes(1));
    const payload = mocks.updateContract.mock.calls[0]?.[1] as Record<string, unknown>;
    expect(payload.rate_client_currency).toBe("GBP");
    for (const operational of [
      "start_date",
      "end_date",
      "status",
      "contract_type",
      "order_consumption",
      "handover_notes",
    ]) {
      expect(payload).not.toHaveProperty(operational);
    }
  });
});

describe("ContractDetailPage — bez edycji kontraktów strona jest do odczytu", () => {
  it("ukrywa mutacje, gdy konto nie ma edycji kontraktów ani zmiany kwot", async () => {
    mocks.access = {
      isAdmin: false,
      canEditContract: false,
      canEditContractStatus: false,
      canReassignClient: false,
    };
    renderPage();

    await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
    expect(screen.queryByRole("button", { name: /Edytuj/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Usuń$/ })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Zmień status kontraktu" }),
    ).not.toBeInTheDocument();
  });

  it("przekazuje tryb „podgląd jako” do wspólnej bramki — to ona chowa mutacje", async () => {
    mocks.impersonating = true;
    renderPage();

    await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
    expect(mocks.accessCalls.length).toBeGreaterThan(0);
    expect(mocks.accessCalls.every((call) => call.impersonating)).toBe(true);
    // Kwoty i dokumenty liczą się per klient kontraktu, nie globalnie.
    expect(mocks.accessCalls.some((call) => call.clientId === 42)).toBe(true);
    // „Przepnij na innego klienta" pilnuje podglądu także lokalnie.
    expect(
      screen.queryByRole("button", { name: /Przepnij na innego klienta/ }),
    ).not.toBeInTheDocument();
  });
});

describe("ContractDetailPage — edycja kontraktu nie daje zmiany statusu", () => {
  // Dwa osobne uprawnienia: „Kontrakty i zamówienia: tworzenie i edycja”
  // (domyślnie także Finanse) i „Zakończenie współpracy, zmiana statusu
  // kontraktu”. Formularz odsyła status przy każdym zapisie, ale zmienić go
  // może tylko posiadacz drugiego.
  const EDIT_WITHOUT_STATUS = {
    isAdmin: false,
    canReassignClient: false,
    canEditContractStatus: false,
  };

  it("formularz edycji blokuje pole Status i mówi, którego uprawnienia brakuje", async () => {
    mocks.access = EDIT_WITHOUT_STATUS;
    const user = userEvent.setup({ delay: null });
    renderPage();

    await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
    await user.click(screen.getByRole("button", { name: /^Edytuj$/ }));

    const status = screen.getByLabelText("Status");
    expect(status).toBeDisabled();
    expect(status).toHaveAttribute(
      "title",
      "Status zmienia osoba z uprawnieniem „Zakończenie współpracy, zmiana statusu kontraktu”",
    );
    // Zapis pozostałych pól działa — status jedzie niezmieniony.
    await user.click(screen.getByRole("button", { name: /Zapisz/ }));
    await waitFor(() => expect(mocks.updateContract).toHaveBeenCalledTimes(1));
    expect(mocks.updateContract.mock.calls[0]?.[1]).toMatchObject({
      status: "active",
    });
  });

  it("posiadacz zmiany statusu ma pole Status aktywne", async () => {
    const user = userEvent.setup({ delay: null });
    renderPage();

    await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
    await user.click(screen.getByRole("button", { name: /^Edytuj$/ }));

    expect(screen.getByLabelText("Status")).toBeEnabled();
  });

  it("„Zakończ wcześniej” w aneksach dostaje tylko posiadacz zmiany statusu", async () => {
    mocks.search = "tab=amendments";
    mocks.access = EDIT_WITHOUT_STATUS;
    const first = renderPage();

    expect(await screen.findByText("zakładka aneksów")).toBeInTheDocument();
    expect(mocks.amendmentsTabProps?.readOnly).toBe(false);
    expect(mocks.amendmentsTabProps?.onRequestTermination).toBeUndefined();

    first.unmount();
    mocks.access = {};
    renderPage();

    expect(await screen.findByText("zakładka aneksów")).toBeInTheDocument();
    expect(mocks.amendmentsTabProps?.onRequestTermination).toBeTypeOf("function");
  });
});

describe("ContractDetailPage — wymuszone usunięcie podpisanego kontraktu", () => {
  it("Admin potwierdza ID i wraca do dokładnego bezpiecznego stanu listy", async () => {
    const user = await requestDelete();

    expect(mocks.deleteContract).toHaveBeenCalledWith(563);
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Usunąć kontrakt?" }),
      ).not.toBeInTheDocument(),
    );

    const forcedDialog = await screen.findByRole("dialog", {
      name: "Wymusić usunięcie podpisanego kontraktu?",
    });
    await user.type(
      within(forcedDialog).getByLabelText(/numer kontraktu.*563/i),
      "563",
    );
    await user.click(
      within(forcedDialog).getByRole("button", {
        name: "Usuń podpisany kontrakt",
      }),
    );

    await waitFor(() =>
      expect(mocks.forceDeleteSigned).toHaveBeenCalledWith(563, "563"),
    );
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith(RETURN_TO));
  });

  it("użytkownik bez roli Admin widzi blokadę i nie dostaje drugiego modala", async () => {
    // Wymuszone usunięcie podpisanego kontraktu zostaje przy roli admina.
    mocks.role = "delivery_lead";
    mocks.access = { isAdmin: false, canReassignClient: false };

    await requestDelete();

    expect(
      await screen.findByText(
        "Usunięcie kontraktu z podpisaną umową jest dostępne wyłącznie dla administratora.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: "Usunąć kontrakt?" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", {
        name: "Wymusić usunięcie podpisanego kontraktu?",
      }),
    ).not.toBeInTheDocument();
    expect(mocks.forceDeleteSigned).not.toHaveBeenCalled();
    expect(mocks.push).not.toHaveBeenCalled();
  });
});

describe("ContractDetailPage — Timeline (retest UAT B23)", () => {
  it("błąd pobrania historii nie udaje pustej historii", async () => {
    mocks.activities.mockRejectedValue({ response: { status: 500 } });
    const user = userEvent.setup({ delay: null });
    renderPage();

    await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
    await user.click(screen.getByRole("button", { name: /Timeline/ }));

    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText("Brak wpisów w historii.")).not.toBeInTheDocument();
  });

  it("pusta odpowiedź nadal mówi, że historii brak", async () => {
    mocks.activities.mockResolvedValue({ data: [] });
    const user = userEvent.setup({ delay: null });
    renderPage();

    await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
    await user.click(screen.getByRole("button", { name: /Timeline/ }));

    expect(await screen.findByText("Brak wpisów w historii.")).toBeInTheDocument();
  });
});

describe("ContractDetailPage — audyt 24.09 (blok D)", () => {
  it("otwiera zakładkę wskazaną w adresie i zapisuje wybór w adresie (S9)", async () => {
    mocks.search = "tab=amendments";
    const user = userEvent.setup({ delay: null });
    renderPage();

    expect(await screen.findByText("zakładka aneksów")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Timeline/ }));
    expect(mocks.replace).toHaveBeenCalledWith(
      expect.stringContaining("tab=timeline"),
      { scroll: false },
    );
  });

  it("tytułem jest osoba, a klient i numer kontraktu stoją w podtytule", async () => {
    renderPage();

    const heading = await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
    expect(heading).not.toHaveTextContent("Kontrakt #563");
    expect(screen.getByText(/Kontrakt #563/)).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: "Nordea" })[0],
    ).toHaveAttribute("href", "/clients/42");
  });

  it("pokazuje „Anulowany” zamiast surowego `void` (S11)", async () => {
    mocks.getContract.mockResolvedValue({ data: { ...contract, status: "void" } });
    renderPage();

    const heading = await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
    expect(within(heading).getAllByText("Anulowany").length).toBeGreaterThan(0);
    expect(within(heading).queryByText("void")).not.toBeInTheDocument();
  });

  it("odmowa zmiany statusu z nagłówka jest widoczna bez trybu edycji (S9)", async () => {
    mocks.updateStatus.mockRejectedValue(new Error("409"));
    const user = userEvent.setup({ delay: null });
    renderPage();

    await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Zmień status kontraktu" }),
      "draft",
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się usunąć kontraktu.",
    );
  });

  it("benchmark tylko z `view_finance` — ta sama bramka co backend (S1)", async () => {
    renderPage();
    expect(await screen.findByText("karta benchmarku")).toBeInTheDocument();
  });

  it("konto bez `view_finance` nie dostaje karty kończącej się 403 (S1)", async () => {
    mocks.access = { canViewBenchmark: false };
    renderPage();
    await screen.findByRole("heading", { name: /Agnieszka Urbaniak/ });
    expect(screen.queryByText("karta benchmarku")).not.toBeInTheDocument();
  });
});
