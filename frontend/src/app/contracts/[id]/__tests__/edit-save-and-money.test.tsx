import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Zapis formularza edycji (stawki, harmonogramy, status, zużycie zamówienia),
// „Generuj z szablonu”, historia stawek w „Pieniądzach” i fakty nagłówka.
// Mocki jak w `signed-delete-flow.test.tsx`: bramki z `lib/contract-access`
// podstawione flagami, ciężkie zakładki zastąpione atrapami.
const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  apiGet: vi.fn(),
  getContract: vi.fn(),
  getDocuments: vi.fn(),
  updateContract: vi.fn(),
  activities: vi.fn(),
  rateHistory: vi.fn(),
  showError: vi.fn(),
  search: "",
  access: {} as Record<string, boolean>,
  compliance: { risk: "none" } as Record<string, unknown>,
  terminationProps: null as null | { defaultDate?: string },
}));

vi.mock("@/lib/contract-access", () => {
  const everything = {
    isAdmin: true,
    canManageFinance: true,
    canViewBenchmark: false,
    canViewInvoices: false,
    canEditContract: true,
    financeAmountsOnly: false,
    canEditContractStatus: true,
    canRecoverTermination: false,
    canViewFinance: true,
    canViewContractDocuments: true,
    canEditContractDocuments: true,
    canReassignClient: true,
  };
  return { contractAccess: () => ({ ...everything, ...mocks.access }) };
});

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "563" }),
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams(mocks.search),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: mocks.showError, showSuccess: vi.fn(), showToast: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/store/auth", async () => {
  const actual = await vi.importActual<typeof import("@/store/auth")>("@/store/auth");
  return {
    ...actual,
    useAuthStore: (selector: (state: unknown) => unknown) =>
      selector({ user: { role: "admin", roles: ["admin"] }, realUser: null, hydrated: true }),
  };
});

vi.mock("@/components/ds/AppModal", () => ({
  AppModal: ({ open, title, children, footer }: { open: boolean; title: string; children: React.ReactNode; footer?: React.ReactNode }) =>
    open ? (
      <section role="dialog" aria-label={title}>
        {children}
        {footer}
      </section>
    ) : null,
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  CONTRACT_FIELD_LABELS: {},
  contractsApi: {
    get: (...args: unknown[]) => mocks.getContract(...args),
    documents: (...args: unknown[]) => mocks.getDocuments(...args),
    activities: (...args: unknown[]) => mocks.activities(...args),
    rateHistory: (...args: unknown[]) => mocks.rateHistory(...args),
    update: (...args: unknown[]) => mocks.updateContract(...args),
    updateStatus: vi.fn(),
    delete: vi.fn(),
    forceDeleteSigned: vi.fn(),
  },
  extractErrorMsg: (err: { response?: { data?: { detail?: string } } }) =>
    err?.response?.data?.detail ?? "Nie udało się zapisać kontraktu.",
  CONTRACT_TERMINATION_REASONS: [{ value: "client_budget", label: "Budżet klienta" }],
}));

vi.mock("@/components/contracts/AddProjectDialog", () => ({ AddProjectDialog: () => null }));
vi.mock("@/components/ContractAmendmentsTab", () => ({
  ContractAmendmentsTab: () => <p>zakładka aneksów</p>,
  NOTICE_WITHDRAWAL_HINT: "",
}));
vi.mock("@/components/ContractDocumentsTab", () => ({
  ContractDocumentsTab: () => null,
  summariseComplianceRisk: () => mocks.compliance,
}));
vi.mock("@/components/ContractEquipmentTab", () => ({ ContractEquipmentTab: () => null }));
vi.mock("@/components/ContractInvoicesTab", () => ({ ContractInvoicesTab: () => <p>faktury konsultanta</p> }));
vi.mock("@/components/ContractOnboardingTab", () => ({ ContractOnboardingTab: () => null }));
vi.mock("@/components/contracts/ContractRateBenchmarkCard", () => ({ ContractRateBenchmarkCard: () => <p>karta benchmarku</p> }));
vi.mock("@/components/contracts/ContractTerminationDialog", () => ({
  ContractTerminationDialog: (props: { defaultDate?: string }) => {
    mocks.terminationProps = props;
    return <p>okno zakończenia współpracy</p>;
  },
}));
vi.mock("@/components/contracts/FinancialRatesCard", () => ({ FinancialRatesCard: () => <p>karta stawek</p> }));
vi.mock("@/components/contracts/FrameworkCategoryCard", () => ({ FrameworkCategoryCard: () => <p>karta umowy ramowej</p> }));

import ContractDetailPage from "../page";
import { HOURS_PER_MONTH } from "@/lib/work-time";

const CONTRACT = {
  id: 563,
  candidate_id: 77,
  client_id: 42,
  job_id: null,
  candidate_name: "Anna Przykładowa",
  client_name: "Firma Testowa sp. z o.o.",
  job_title: null,
  start_date: "2026-01-01",
  end_date: "2026-12-31",
  client_order_end_date: null,
  rate_candidate: 800,
  rate_client: 1000,
  candidate_rate_schedule: [] as unknown[],
  client_rate_schedule: [] as unknown[],
  framework_rate_schedule: [] as unknown[],
  framework_rate: null,
  target_rate_min: null,
  target_rate_max: null,
  currency: "PLN",
  rate_client_currency: "PLN",
  rate_candidate_currency: "PLN",
  eur_pln_rate: null,
  rate_unit: "daily",
  billing_hours_per_month: 160,
  margin: null,
  contract_type: "uop",
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
  related_contracts: [] as unknown[],
};

function renderPage(contract: Record<string, unknown> = {}) {
  mocks.getContract.mockResolvedValue({ data: { ...CONTRACT, ...contract } });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ContractDetailPage />
    </QueryClientProvider>,
  );
}

async function startEdit(contract: Record<string, unknown> = {}) {
  const user = userEvent.setup({ delay: null });
  renderPage(contract);
  await screen.findByRole("heading", { name: /Anna Przykładowa/ });
  await user.click(screen.getByRole("button", { name: /^Edytuj$/ }));
  return user;
}

async function save(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Zapisz" }));
  await waitFor(() => expect(mocks.updateContract).toHaveBeenCalled());
  return mocks.updateContract.mock.calls[0][1] as Record<string, unknown>;
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.access = {};
  mocks.search = "";
  mocks.compliance = { risk: "none" };
  mocks.terminationProps = null;
  window.history.replaceState({}, "", "/contracts/563");
  mocks.apiGet.mockResolvedValue({ data: [] });
  mocks.getDocuments.mockResolvedValue({ data: [] });
  mocks.activities.mockResolvedValue({ data: [] });
  mocks.rateHistory.mockResolvedValue({ data: [] });
  mocks.updateContract.mockResolvedValue({ data: CONTRACT });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Edycja kontraktu — stawki", () => {
  it("stawki z przecinkiem idą jako liczby; obce znaki są wycinane z pola", async () => {
    const user = await startEdit();
    const client = screen.getByLabelText("Stawka klienta");
    await user.clear(client);
    await user.type(client, "1 2a34,5,6");
    expect(client).toHaveValue("1234,56");
    await user.clear(screen.getByLabelText("Stawka kandydata"));
    await user.type(screen.getByLabelText("Stawka kandydata"), "950,5");
    await user.type(screen.getByLabelText("Stawka z umowy ramowej"), "1100");
    const payload = await save(user);
    expect(payload).toMatchObject({
      rate_client: 1234.56,
      rate_candidate: 950.5,
      framework_rate: 1100,
      rate_unit: "daily",
      billing_hours_per_month: 160,
    });
    expect(payload).not.toHaveProperty("candidate_rate_schedule");
    expect(payload).not.toHaveProperty("framework_rate_schedule");
  });

  it("puste stawki to null, a nie zero", async () => {
    const user = await startEdit();
    await user.clear(screen.getByLabelText("Stawka klienta"));
    await user.clear(screen.getByLabelText("Stawka kandydata"));
    const payload = await save(user);
    expect(payload.rate_client).toBeNull();
    expect(payload.rate_candidate).toBeNull();
    expect(payload.framework_rate).toBeNull();
  });

  it("stawka godzinowa: puste pole godzin wraca do domyślnej liczby godzin w miesiącu", async () => {
    const user = await startEdit();
    await user.selectOptions(screen.getByLabelText("Jednostka stawki"), "hourly");
    const hours = screen.getByLabelText("Godziny / miesiąc");
    await user.clear(hours);
    const payload = await save(user);
    expect(payload.rate_unit).toBe("hourly");
    expect(payload.billing_hours_per_month).toBe(HOURS_PER_MONTH);
  });

  it("„Dodaj stawkę progresywną” zakłada harmonogram: pierwszy etap od startu umowy, drugi od wpisanej daty", async () => {
    const user = await startEdit();
    await user.click(screen.getByRole("button", { name: /Dodaj stawkę progresywną/ }));
    expect(screen.getByLabelText("Etap 1 stawki kandydata: kwota")).toHaveValue("800");
    await user.type(screen.getByLabelText("Etap 2 stawki kandydata: kwota"), "900");
    await user.type(screen.getByLabelText("Etap 2 stawki kandydata: obowiązuje od"), "2026-07-01");
    const payload = await save(user);
    expect(payload).not.toHaveProperty("rate_candidate");
    expect(payload.candidate_rate_schedule).toEqual([
      { rate: 800, effective_from: "2026-01-01", effective_to: null, note: null },
      { rate: 900, effective_from: "2026-07-01", effective_to: null, note: null },
    ]);
  });

  it("jeden etap bez daty to zwykła stawka, nie harmonogram", async () => {
    const user = await startEdit();
    await user.click(screen.getByRole("button", { name: /Dodaj stawkę progresywną/ }));
    await user.click(screen.getByRole("button", { name: "Usuń etap 2 stawki kandydata" }));
    const payload = await save(user);
    expect(payload).not.toHaveProperty("candidate_rate_schedule");
    expect(payload.rate_candidate).toBe(800);
  });

  it("niezmieniony zapisany harmonogram nie idzie do API (notatki i autorzy zostają)", async () => {
    const schedule = [
      { id: 1, rate: 800, effective_from: "2026-01-01", effective_to: null, note: "start", created_at: "2026-01-01T00:00:00Z" },
      { id: 2, rate: 900, effective_from: "2026-07-01", effective_to: null, note: "aneks", created_at: "2026-06-01T00:00:00Z" },
    ];
    const user = await startEdit({ candidate_rate_schedule: schedule });
    expect(screen.getByLabelText("Etap 2 stawki kandydata: kwota")).toHaveValue("900");
    await user.type(screen.getByLabelText("Notatki wewnętrzne (widoczne tylko dla TAC/delivery)"), "x");
    const payload = await save(user);
    expect(payload).not.toHaveProperty("candidate_rate_schedule");
    expect(payload).not.toHaveProperty("rate_candidate");
  });

  it("zmieniony harmonogram idzie w całości; usunięty do zera — pusta lista i zwykła stawka", async () => {
    const schedule = [
      { id: 1, rate: 800, effective_from: "2026-01-01", effective_to: null, note: null, created_at: "2026-01-01T00:00:00Z" },
      { id: 2, rate: 900, effective_from: "2026-07-01", effective_to: null, note: null, created_at: "2026-06-01T00:00:00Z" },
    ];
    const user = await startEdit({ candidate_rate_schedule: schedule });
    const second = screen.getByLabelText("Etap 2 stawki kandydata: kwota");
    await user.clear(second);
    await user.type(second, "950");
    const payload = await save(user);
    expect(payload.candidate_rate_schedule).toEqual([
      { rate: 800, effective_from: "2026-01-01", effective_to: null, note: null },
      { rate: 950, effective_from: "2026-07-01", effective_to: null, note: null },
    ]);
  });

  it("usunięcie wszystkich etapów wysyła pustą listę i stawkę z pola", async () => {
    const schedule = [
      { id: 1, rate: 800, effective_from: "2026-01-01", effective_to: null, note: null, created_at: "2026-01-01T00:00:00Z" },
      { id: 2, rate: 900, effective_from: "2026-07-01", effective_to: null, note: null, created_at: "2026-06-01T00:00:00Z" },
    ];
    const user = await startEdit({ candidate_rate_schedule: schedule });
    await user.click(screen.getByRole("button", { name: "Usuń etap 2 stawki kandydata" }));
    await user.click(screen.getByRole("button", { name: "Usuń etap 1 stawki kandydata" }));
    const payload = await save(user);
    expect(payload.candidate_rate_schedule).toEqual([]);
    expect(payload).toHaveProperty("rate_candidate");
  });

  it("harmonogram stawki ramowej działa tak samo jak kandydata", async () => {
    const user = await startEdit({ framework_rate: 1100 });
    await user.click(screen.getByRole("button", { name: /Dodaj etap stawki ramowej/ }));
    await user.type(screen.getByLabelText("Etap 2 stawki z umowy ramowej: kwota"), "1200,5");
    await user.type(screen.getByLabelText("Etap 2 stawki z umowy ramowej: obowiązuje od"), "2027-01-01");
    const payload = await save(user);
    expect(payload).not.toHaveProperty("framework_rate");
    expect(payload.framework_rate_schedule).toEqual([
      { rate: 1100, effective_from: "2026-01-01", effective_to: null, note: null },
      { rate: 1200.5, effective_from: "2027-01-01", effective_to: null, note: null },
    ]);
  });

  it("stawka klienta z harmonogramem jest zablokowana (zmiana aneksem)", async () => {
    await startEdit({
      client_rate_schedule: [{ id: 3, rate: 1000, effective_from: "2026-01-01", note: null, created_at: "2026-01-01T00:00:00Z" }],
    });
    expect(screen.getByLabelText("Stawka klienta")).toBeDisabled();
  });

  it("konto „tylko kwoty” wysyła wyłącznie pola kwot", async () => {
    mocks.access = { canEditContract: false, financeAmountsOnly: true };
    const user = userEvent.setup({ delay: null });
    renderPage();
    await user.click(await screen.findByRole("button", { name: /Edytuj stawki/ }));
    expect(screen.getByRole("heading", { name: "Edycja stawek" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Data rozpoczęcia")).not.toBeInTheDocument();
    const payload = await save(user);
    expect(payload).not.toHaveProperty("status");
    expect(payload).not.toHaveProperty("start_date");
    expect(payload).toHaveProperty("rate_client", 1000);
  });

  it("bez zarządzania finansami formularz nie ma pól stawek i nie wysyła kwot", async () => {
    mocks.access = { canManageFinance: false };
    const user = await startEdit();
    expect(screen.queryByLabelText("Stawka klienta")).not.toBeInTheDocument();
    const payload = await save(user);
    expect(payload).not.toHaveProperty("rate_client");
    expect(payload).not.toHaveProperty("rate_candidate");
  });
});

describe("Edycja kontraktu — pola operacyjne i status", () => {
  it("zużycie zamówienia z jednostką; puste zużycie zeruje też jednostkę", async () => {
    const user = await startEdit();
    await user.type(screen.getByLabelText("Zużycie zamówienia"), "12,5");
    await user.selectOptions(screen.getByLabelText("Jednostka zużycia"), "md");
    await user.selectOptions(screen.getByLabelText("Okres wypowiedzenia (mies.)"), "3");
    const payload = await save(user);
    expect(payload).toMatchObject({ order_consumption: 12.5, order_consumption_unit: "md", notice_period_months: 3 });
    expect(payload.end_date).toBe("2026-12-31");
    expect(payload.client_order_end_date).toBeNull();
    expect(payload.handover_notes).toBeNull();
  });

  it("puste zużycie i okres wypowiedzenia to null", async () => {
    const user = await startEdit({ order_consumption: 10, order_consumption_unit: "md", notice_period_months: 1 });
    await user.clear(screen.getByLabelText("Zużycie zamówienia"));
    await user.selectOptions(screen.getByLabelText("Okres wypowiedzenia (mies.)"), "");
    const payload = await save(user);
    expect(payload.order_consumption).toBeNull();
    expect(payload.order_consumption_unit).toBeNull();
    expect(payload.notice_period_months).toBeNull();
  });

  it("umowa B2B bez zakończenia jest bezterminowa: bez pola daty końca i z null w zapisie", async () => {
    const user = await startEdit({ contract_type: "b2b" });
    expect(screen.getByTestId("end-date-b2b-indefinite")).toHaveTextContent(/Bezterminowo/);
    // „Kończący się” wymaga daty końca — dla bezterminowej B2B nie ma go na liście.
    expect(within(screen.getByLabelText("Status")).queryByRole("option", { name: "Kończący się" })).not.toBeInTheDocument();
    const payload = await save(user);
    expect(payload.end_date).toBeNull();
  });

  it("okres zamówienia z synchronizacji nie idzie w zapisie ręcznym", async () => {
    const user = await startEdit({ client_order_start_date: "2026-01-01", client_order_end_date: "2026-06-30" });
    expect(screen.getByLabelText("Koniec zamówienia u klienta")).toHaveAttribute("readonly");
    const payload = await save(user);
    expect(payload).not.toHaveProperty("client_order_end_date");
  });

  it("zmiana statusu na „Zakończony” otwiera okno zakończenia z datą z formularza zamiast zapisu", async () => {
    const user = await startEdit();
    const end = screen.getByLabelText("Data zakończenia");
    await user.clear(end);
    await user.type(end, "2026-11-30");
    await user.selectOptions(screen.getByLabelText("Status"), "ended");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(await screen.findByText("okno zakończenia współpracy")).toBeInTheDocument();
    expect(mocks.terminationProps?.defaultDate).toBe("2026-11-30");
    expect(mocks.updateContract).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Status")).toHaveValue("active");
  });

  it("zakończonego kontraktu nie przywraca zmiana statusu w formularzu", async () => {
    const user = await startEdit({ status: "ended", termination_reason: "client_budget", terminated_at: "2026-10-31T10:00:00Z" });
    await user.selectOptions(screen.getByLabelText("Status"), "active");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(await screen.findByText(/przywracasz akcją „Cofnij zakończenie”/)).toBeInTheDocument();
    expect(mocks.updateContract).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Status")).toHaveValue("ended");
  });

  it("odmowa zapisu pokazuje powód z API i zostawia formularz", async () => {
    mocks.updateContract.mockRejectedValue({ response: { status: 409, data: { detail: "Brakuje: Data rozpoczęcia" } } });
    const user = await startEdit();
    await user.clear(screen.getByLabelText("Data rozpoczęcia"));
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(await screen.findByText("Brakuje: Data rozpoczęcia")).toBeInTheDocument();
    expect(mocks.updateContract.mock.calls[0][1]).toMatchObject({ start_date: null });
    expect(screen.getByRole("heading", { name: "Edycja kontraktu" })).toBeInTheDocument();
  });

  it("„Anuluj” zamyka formularz bez zapisu", async () => {
    const user = await startEdit();
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(screen.queryByRole("heading", { name: "Edycja kontraktu" })).not.toBeInTheDocument();
    expect(mocks.updateContract).not.toHaveBeenCalled();
  });
});

describe("Kontrakt — Pieniądze i fakty", () => {
  it("historia stawek z wcześniejszych umów: kwota w walucie, brak końca i notatki jako „—”", async () => {
    mocks.search = "tab=money";
    mocks.rateHistory.mockResolvedValue({
      data: [
        { id: 1, rate: 850, currency: "PLN", contract_type: "b2b", start_date: "2024-01-01", end_date: "2024-12-31", notes: "Poprzedni projekt", created_at: "2024-01-01T00:00:00Z" },
        { id: 2, rate: 0, currency: "EUR", contract_type: "uop", start_date: "2025-01-01", end_date: null, notes: null, created_at: "2025-01-01T00:00:00Z" },
      ],
    });
    renderPage();
    const heading = await screen.findByRole("heading", { name: "Stawki z wcześniejszych umów u tego klienta" });
    const table = within(heading.parentElement!).getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("01.01.2024");
    expect(rows[0]).toHaveTextContent("31.12.2024");
    expect(rows[0]).toHaveTextContent("Poprzedni projekt");
    expect(rows[0].textContent).toMatch(/850/);
    expect(within(rows[1]).getAllByText("—")).toHaveLength(2);
    expect(rows[1].textContent).toMatch(/0[,.]00|0\s?€|EUR/);
    expect(mocks.rateHistory).toHaveBeenCalledWith(563);
    expect(screen.getByText("karta stawek")).toBeInTheDocument();
  });

  it("bez widoku kwot zakładka „Pieniądze” nie pyta o historię stawek", async () => {
    mocks.access = { canViewFinance: false, canViewInvoices: true };
    mocks.search = "tab=money";
    renderPage();
    expect(await screen.findByText("faktury konsultanta")).toBeInTheDocument();
    expect(screen.queryByText("karta stawek")).not.toBeInTheDocument();
    expect(mocks.rateHistory).not.toHaveBeenCalled();
  });

  it("osoba u dwóch klientów: chipy kontraktów i „pracuje u 2 klientów”", async () => {
    renderPage({
      related_contracts: [
        { id: 600, client_id: 43, client_name: "Klient Testowy S.A.", status: "active", start_date: "2026-03-01", end_date: null },
        { id: 601, client_id: 44, client_name: null, status: "ended", start_date: "2025-01-01", end_date: "2025-12-31" },
      ],
    });
    await screen.findByRole("heading", { name: /Anna Przykładowa/ });
    expect(screen.getByText("pracuje u 2 klientów")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Klient Testowy S\.A\./ })).toHaveAttribute("href", "/contracts/600");
    expect(screen.getByRole("link", { name: /Klient #44/ })).toHaveAttribute("href", "/contracts/601");
  });

  it("widełki docelowe w walucie klienta; tryb pracy i biuro; powrót po przerwie", async () => {
    renderPage({
      target_rate_min: 900,
      target_rate_max: null,
      rate_client_currency: "EUR",
      work_mode: "hybrid",
      office_location: "Kraków",
      returned_from_contract_id: 500,
      project_name: "Projekt Testowy",
    });
    await screen.findByRole("heading", { name: /Anna Przykładowa/ });
    const range = screen.getByText("Widełki docelowe stawki").closest("div")!;
    expect(range.textContent).toMatch(/900/);
    expect(range.textContent).toMatch(/EUR|€/);
    expect(range.textContent).toMatch(/\/ —/);
    expect(screen.getByText("Hybrydowo · Kraków")).toBeInTheDocument();
    expect(screen.getByText("POWRÓT PO PRZERWIE")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "poprzedni kontrakt #500" })).toHaveAttribute("href", "/contracts/500");
    expect(screen.getByText("Projekt Testowy")).toBeInTheDocument();
  });

  it("kontrakt bez kandydata w systemie nie linkuje do /candidates/null", async () => {
    renderPage({ candidate_id: null, candidate_name: null });
    expect(await screen.findByRole("heading", { name: /Kontrakt #563/ })).toBeInTheDocument();
    expect(document.querySelector('a[href="/candidates/null"]')).toBeNull();
  });

  it("dokument po terminie i dokument wygasający mają plakietki compliance", async () => {
    mocks.compliance = { risk: "overdue", soonestDate: null, docType: null };
    renderPage();
    expect(await screen.findByText("Compliance: dokument wygasł")).toBeInTheDocument();
  });

  it("dokument wygasający pokazuje typ i datę", async () => {
    mocks.compliance = { risk: "soon", soonestDate: "2026-12-01", docType: "KRK" };
    renderPage();
    expect(await screen.findByText("Compliance: KRK wygasa 01.12.2026")).toBeInTheDocument();
  });
});

describe("Kontrakt — „Generuj z szablonu”", () => {
  function templates() {
    mocks.apiGet.mockImplementation(async (url: string) => {
      if (url === "/api/contract-templates") return { data: [{ id: 9, name: "Umowa UoP — wzór", contract_type: "uop" }] };
      return { data: [] };
    });
  }

  async function pickTemplate() {
    const user = userEvent.setup({ delay: null });
    renderPage();
    await screen.findByRole("heading", { name: /Anna Przykładowa/ });
    await user.click(screen.getByRole("button", { name: "Więcej akcji" }));
    await user.click(await screen.findByRole("menuitem", { name: /Generuj z szablonu/ }));
    // Pozycja podmenu Radixa wybiera się klawiaturą (klik w jsdom nie domyka wyboru).
    const item = await screen.findByRole("menuitem", { name: "Umowa UoP — wzór" });
    item.focus();
    await user.keyboard("{Enter}");
  }

  it("pyta o szablony typu umowy i otwiera wyrenderowany dokument w nowym oknie", async () => {
    templates();
    const doc = { write: vi.fn(), close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue({ document: doc } as unknown as Window);
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, text: async () => "<p>umowa</p>" }));
    vi.stubGlobal("fetch", fetchMock);
    await pickTemplate();
    await waitFor(() => expect(doc.write).toHaveBeenCalledWith("<p>umowa</p>"));
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/contract-templates", { params: { contract_type: "uop" } });
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toMatch(/\/api\/contract-templates\/9\/render\?contract_id=563$/);
    expect(doc.close).toHaveBeenCalled();
  });

  it("błąd HTTP i zablokowane okno idą komunikatem, nie natywnym alertem", async () => {
    templates();
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 500, text: async () => "" })));
    await pickTemplate();
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Nie udało się wygenerować dokumentu (HTTP 500)."));
  });

  it("zablokowane wyskakujące okno mówi, co zrobić", async () => {
    templates();
    vi.spyOn(window, "open").mockReturnValue(null);
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, text: async () => "<p/>" })));
    await pickTemplate();
    await waitFor(() =>
      expect(mocks.showError).toHaveBeenCalledWith(
        "Przeglądarka zablokowała nowe okno — zezwól na wyskakujące okna i spróbuj ponownie.",
      ),
    );
  });

  it("awaria sieci mówi, co się stało", async () => {
    templates();
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new Error("brak sieci");
    }));
    await pickTemplate();
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Nie udało się wygenerować dokumentu: brak sieci"));
  });

  it("bez szablonów dla typu umowy pozycji nie ma", async () => {
    const user = userEvent.setup({ delay: null });
    renderPage();
    await screen.findByRole("heading", { name: /Anna Przykładowa/ });
    await user.click(screen.getByRole("button", { name: "Więcej akcji" }));
    await screen.findByRole("menuitem", { name: /Usuń kontrakt/ });
    expect(screen.queryByRole("menuitem", { name: /Generuj z szablonu/ })).not.toBeInTheDocument();
  });
});
