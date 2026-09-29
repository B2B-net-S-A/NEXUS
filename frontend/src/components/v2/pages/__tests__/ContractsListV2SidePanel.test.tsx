/**
 * Rejestr kontraktów, wersja B (29.09.2026): klik w wiersz otwiera boczny
 * panel kontraktu, wybór stoi w adresie (`?contract=`), a linki, kwadraciki
 * i Esc działają jak wcześniej.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  contractGet: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/contracts",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    default: {
      get: (...args: unknown[]) => mocks.get(...args),
      post: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
    },
    contractsApi: {
      get: (...args: unknown[]) => mocks.contractGet(...args),
      documents: () => Promise.resolve({ data: [] }),
      activities: () => Promise.resolve({ data: [] }),
      update: vi.fn(),
      updateStatus: vi.fn(),
    },
  };
});

import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";
import { useAuthStore } from "@/store/auth";

const member = (over: Record<string, unknown>) => ({
  client_name: null,
  job_title: null,
  start_date: "2026-07-01",
  end_date: null,
  latest_order_end_date: null,
  contract_type: "b2b",
  rate_candidate: 125,
  rate_client: 175,
  margin: 50,
  rate_unit: "hourly",
  currency: "PLN",
  status: "active",
  ...over,
});

const LIST = {
  items: [
    {
      id: 467,
      candidate_id: 10,
      candidate_name: "Paweł Przykładowy",
      client_name: "Bank Sigma",
      status: "active",
      contract_type: "b2b",
      group_members: [
        member({ id: 512, client_id: 2, client_name: "Bank Omega" }),
        member({ id: 467, client_id: 1, client_name: "Bank Sigma" }),
      ],
    },
    {
      id: 300,
      candidate_id: 11,
      candidate_name: "Jan Testowy",
      client_name: "Trzeci Klient",
      status: "active",
      contract_type: "b2b",
      group_members: [member({ id: 300, client_id: 3, client_name: "Trzeci Klient" })],
    },
  ],
  total: 2,
  contractors_total: 2,
  contracts_total: 3,
  page: 1,
  page_size: 20,
};

function detail(id: number) {
  return {
    id,
    candidate_id: 10,
    client_id: 1,
    candidate_name: id === 300 ? "Jan Testowy" : "Paweł Przykładowy",
    client_name: `Klient ${id}`,
    job_title: null,
    start_date: "2026-07-01",
    end_date: null,
    client_order_start_date: "2026-07-01",
    client_order_end_date: "2031-12-31",
    rate_candidate: 125,
    rate_client: 175,
    margin: 50,
    rate_unit: "hourly",
    billing_hours_per_month: 168,
    currency: "PLN",
    contract_type: "b2b",
    status: "active",
    related_contracts: [],
  };
}

// Panel ładuje się leniwie (`next/dynamic`) — pierwszy import w przebiegu trwa
// dłużej niż domyślna sekunda `findBy`.
const PANEL_LOAD = { timeout: 8000 };

function renderList() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ContractsListV2 />
    </QueryClientProvider>,
  );
}

function memberRow(id: number): HTMLElement {
  const row = document.querySelector<HTMLElement>(`[data-contract-member="${id}"]`);
  if (!row) throw new Error(`brak wiersza ${id}`);
  return row;
}

describe("ContractsListV2 — boczny panel kontraktu", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/contracts");
    window.sessionStorage.clear();
    useAuthStore.setState({
      user: {
        id: 1,
        email: "admin@example.com",
        name: "Admin",
        role: "admin",
        roles: ["admin"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        capabilities: ["view_finance", "contract.create"],
        analytics_capabilities: ["view_finance"],
      } as never,
      hydrated: true,
    });
    mocks.get.mockReset();
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({ data: url === "/api/contracts" ? LIST : [] }),
    );
    mocks.contractGet.mockReset();
    mocks.contractGet.mockImplementation((id: number) => Promise.resolve({ data: detail(id) }));
  });

  afterEach(() => {
    useAuthStore.setState({ user: null, hydrated: true });
  });

  it("klik w pas klienta otwiera panel TEGO kontraktu i zapisuje `?contract=`", async () => {
    renderList();
    await screen.findByText("Paweł Przykładowy");

    fireEvent.click(memberRow(512).querySelector('[data-label="Typ"]') as HTMLElement);
    const panel = await screen.findByTestId("contract-side-panel", {}, PANEL_LOAD);
    expect(panel).toBeInTheDocument();
    await waitFor(() => expect(mocks.contractGet).toHaveBeenCalledWith(512));
    expect(window.location.search).toContain("contract=512");
    // Filtry i strona zostają — wybór nie jest zawężeniem listy.
    expect(window.location.search).toContain("status=active&status=ending");
    expect(memberRow(512)).toHaveAttribute("aria-selected", "true");
    expect(memberRow(467)).toHaveAttribute("aria-selected", "false");
  });

  it("komórka osoby otwiera umowę główną, nie pas, w którym leży", async () => {
    renderList();
    await screen.findByText("Paweł Przykładowy");
    const candidateCell = within(memberRow(512))
      .getByRole("link", { name: "Paweł Przykładowy" })
      .closest("td") as HTMLElement;
    fireEvent.click(candidateCell);
    await screen.findByTestId("contract-side-panel", {}, PANEL_LOAD);
    await waitFor(() => expect(mocks.contractGet).toHaveBeenCalledWith(467));
    expect(window.location.search).toContain("contract=467");
  });

  it("kwadracik zaznaczenia nie otwiera panelu", async () => {
    const user = userEvent.setup();
    renderList();
    await screen.findByText("Paweł Przykładowy");
    await user.click(
      screen.getByRole("checkbox", { name: /Zaznacz wszystkie kontrakty: Paweł Przykładowy/ }),
    );
    expect(screen.queryByTestId("contract-side-panel")).not.toBeInTheDocument();
    expect(window.location.search).not.toContain("contract=");
  });

  it("nazwisko i klient zostają linkami do karty kontraktu (bez otwierania panelu)", async () => {
    renderList();
    await screen.findByText("Paweł Przykładowy");
    const name = screen.getByRole("link", { name: "Paweł Przykładowy" });
    expect(name.getAttribute("href")).toContain("/contracts/467?from=contracts");
    const client = within(memberRow(512)).getByRole("link", { name: /Bank Omega/ });
    expect(client.getAttribute("href")).toContain("/contracts/512?from=contracts");
    fireEvent.click(client);
    expect(screen.queryByTestId("contract-side-panel")).not.toBeInTheDocument();
  });

  it("Esc zamyka panel i zdejmuje `?contract=` z adresu", async () => {
    renderList();
    await screen.findByText("Paweł Przykładowy");
    fireEvent.click(memberRow(300));
    await screen.findByTestId("contract-side-panel", {}, PANEL_LOAD);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByTestId("contract-side-panel")).not.toBeInTheDocument(),
    );
    expect(window.location.search).not.toContain("contract=");
  });

  it("`?contract=` w adresie otwiera panel od razu", async () => {
    window.history.replaceState({}, "", "/contracts?status=active&status=ending&contract=300");
    renderList();
    expect(await screen.findByTestId("contract-side-panel", {}, PANEL_LOAD)).toBeInTheDocument();
    await waitFor(() => expect(mocks.contractGet).toHaveBeenCalledWith(300));
  });

  it("↓ przestawia panel na kolejny wiersz", async () => {
    renderList();
    await screen.findByText("Paweł Przykładowy");
    fireEvent.click(memberRow(467));
    await screen.findByTestId("contract-side-panel", {}, PANEL_LOAD);
    memberRow(467).focus();
    fireEvent.keyDown(window, { key: "ArrowDown" });
    await waitFor(() => expect(window.location.search).toContain("contract=300"));
    expect(memberRow(300)).toHaveAttribute("data-selected", "true");
  });
});
