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
  canManageFinance: false,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "563" }),
  useRouter: () => ({ push: mocks.push }),
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

vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (state: {
      user: { role: string; roles: string[] };
      hydrated: boolean;
    }) => unknown,
  ) =>
    selector({
      user: { role: mocks.role, roles: [mocks.role] },
      hydrated: true,
    }),
  hasRole: (
    _user: unknown,
    ...roles: string[]
  ) => roles.includes(mocks.role),
  canManageCandidateFinance: () => mocks.canManageFinance,
  canViewCandidateFinance: () => mocks.role === "admin",
}));

vi.mock("@/components/RequireRole", () => ({
  RequireRole: ({
    roles,
    children,
  }: {
    roles?: string[];
    children: React.ReactNode;
  }) => (roles && !roles.includes(mocks.role) ? null : children),
}));

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
  contractsApi: {
    get: (...args: unknown[]) => mocks.getContract(...args),
    documents: (...args: unknown[]) => mocks.getDocuments(...args),
    activities: vi.fn(),
    rateHistory: vi.fn(),
    update: (...args: unknown[]) => mocks.updateContract(...args),
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
  ContractAmendmentsTab: () => null,
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
  ContractRateBenchmarkCard: () => null,
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

  await screen.findByRole("heading", { name: /Kontrakt #563/ });
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
  mocks.canManageFinance = false;
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
    mocks.canManageFinance = true;
    const user = userEvent.setup({ delay: null });
    renderPage();

    await screen.findByRole("heading", { name: /Kontrakt #563/ });
    await user.click(screen.getByRole("button", { name: /Edytuj/ }));

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
    mocks.role = "delivery_lead";

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
