/**
 * „Zamówione po końcu” na liście kontraktów (decyzja Artura 19.11.2026):
 * kubełek liczy serwer (`bucket=order_after_end`), pigułka stoi w rzędzie
 * tylko wtedy, gdy zbiór nie jest pusty, a wiersz mówi, co klient zamówił.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";
import { orderAfterEndNoteText } from "@/components/contracts/OrderAfterEndRowNote";
import { useAuthStore } from "@/store/auth";

const mocks = vi.hoisted(() => ({ get: vi.fn(), stats: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => mocks.get(...args),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  contractorsApi: { stats: () => mocks.stats() },
  phase5Api: {},
  pipelineTemplatesApi: {},
  requestHistoryApi: {},
}));

vi.mock("@/components/contracts/ContractSidePanel", () => ({
  ContractSidePanel: (props: { contractId: number }) => (
    <div data-testid="contract-side-panel">panel {props.contractId}</div>
  ),
}));

type Row = { id: number; candidate_name: string; status: string; afterEnd?: boolean };

const member = (row: Row) => ({
  id: row.id,
  client_id: 1,
  client_name: "Bank Przykładowy",
  job_title: null,
  start_date: "2026-01-01",
  end_date: "2026-11-30",
  latest_order_end_date: null,
  contract_type: "b2b",
  rate_candidate: null,
  rate_client: null,
  margin: null,
  rate_unit: "hourly",
  currency: "PLN",
  rate_client_currency: "PLN",
  rate_candidate_currency: "PLN",
  status: row.status,
});

const toItem = (row: Row) => ({
  ...member(row),
  candidate_id: row.id + 1000,
  candidate_name: row.candidate_name,
  missing_fields: [],
  group_members: [member(row)],
  order_after_end: row.afterEnd
    ? {
        contract_id: row.id,
        order_id: 894,
        status: "draft",
        start_date: "2026-12-01",
        end_date: "2027-05-31",
        count: 1,
      }
    : null,
});

const RUNNING: Row[] = [{ id: 801, candidate_name: "Paweł Aktywny", status: "active" }];
const AFTER_END: Row[] = [
  { id: 802, candidate_name: "Ola Pokońcu", status: "ending", afterEnd: true },
];

type Params = { status?: string[]; bucket?: string };

let afterEndRows: Row[] = AFTER_END;

function respond(params: Params) {
  const rows =
    params.bucket === "order_after_end"
      ? afterEndRows
      : params.bucket
        ? []
        : [...RUNNING, ...AFTER_END];
  return {
    items: rows.map(toItem),
    total: rows.length,
    contractors_total: rows.length,
    contracts_total: rows.length,
    page: 1,
    page_size: 20,
  };
}

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

const quickFilters = () => screen.getByRole("group", { name: "Szybkie filtry kontraktów" });
const contractCalls = () =>
  mocks.get.mock.calls
    .filter((call) => call[0] === "/api/contracts")
    .map((call) => (call[1]?.params ?? {}) as Record<string, unknown>);

describe("ContractsListV2 — „Zamówione po końcu” (19.11.2026)", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/contracts");
    window.sessionStorage.clear();
    afterEndRows = AFTER_END;
    useAuthStore.setState({
      user: {
        id: 9,
        email: "admin@example.com",
        name: "admin",
        role: "admin",
        roles: ["admin"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        capabilities: [],
        analytics_capabilities: [],
      },
      realUser: null,
      hydrated: true,
    } as never);
    mocks.get.mockReset();
    mocks.get.mockImplementation((url: string, config?: { params?: Params }) => {
      if (url === "/api/contracts") {
        return Promise.resolve({ data: respond(config?.params ?? {}) });
      }
      return Promise.resolve({ data: [] });
    });
    mocks.stats.mockReset();
    mocks.stats.mockResolvedValue({ data: { drafts_incomplete: 0 } });
  });

  afterEach(() => {
    useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
  });

  it("pigułka z licznikiem filtruje listę zbiorem serwera i zapisuje adres", async () => {
    renderList();
    const pill = await within(quickFilters()).findByRole("button", {
      name: /^Zamówione po końcu/,
    });
    await waitFor(() => expect(pill).toHaveTextContent("1"));
    expect(contractCalls()).toContainEqual(
      expect.objectContaining({ bucket: "order_after_end", page_size: 1 }),
    );

    fireEvent.click(pill);

    await waitFor(() => expect(screen.queryByText("Paweł Aktywny")).not.toBeInTheDocument());
    expect(screen.getByText("Ola Pokońcu")).toBeInTheDocument();
    expect(pill).toHaveAttribute("aria-pressed", "true");
    expect(window.location.search).toBe("?status=all&after_end=1");
    const note = screen.getByTestId("order-after-end-row-note");
    expect(note).toHaveTextContent("po końcu · 01.12");
    expect(note).toHaveAttribute(
      "title",
      "Klient zamówił okres po zakończeniu współpracy: szkic zamówienia 01.12.2026 – 31.05.2027. Decyzja na karcie kontraktu.",
    );
  });

  it("pusty zbiór nie zajmuje miejsca w rzędzie pigułek", async () => {
    afterEndRows = [];
    renderList();
    await screen.findByText("Paweł Aktywny");
    await waitFor(() =>
      expect(within(quickFilters()).getByRole("button", { name: /^Wszystkie/ })).toHaveTextContent(
        "2",
      ),
    );
    expect(
      within(quickFilters()).queryByRole("button", { name: /^Zamówione po końcu/ }),
    ).not.toBeInTheDocument();
  });

  it("link ?after_end=1 otwiera listę z tym zbiorem", async () => {
    window.history.replaceState({}, "", "/contracts?after_end=1");
    renderList();

    expect(await screen.findByText("Ola Pokońcu")).toBeInTheDocument();
    expect(
      within(quickFilters()).getByRole("button", { name: /^Zamówione po końcu/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(contractCalls()).toContainEqual(
      expect.objectContaining({ bucket: "order_after_end", status: undefined, page: 1 }),
    );
  });
});

describe("notka wiersza „po końcu”", () => {
  it("aktywne zamówienie bez końca i kilka zamówień", () => {
    expect(
      orderAfterEndNoteText({
        contract_id: 1,
        order_id: 2,
        status: "active",
        start_date: "2026-11-02",
        end_date: null,
        count: 2,
      }),
    ).toBe("po końcu · 02.11 (+1)");
  });
});
