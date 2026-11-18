/**
 * Jedna lista kontraktów (decyzja Artura 18.11.2026): szybkie filtry zamiast
 * trybów „Obsługa kontraktorów” / „Rejestr kontraktów”, „Kończące się” liczone
 * jedną regułą serwera (`bucket=ending`), bez banera z trzecią definicją,
 * a „Uzupełnij / Aktywuj” szkicu przeniesione do wiersza listy.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  ContractsListV2,
  draftRowAction,
  missingCountLabel,
} from "@/components/v2/pages/ContractsListV2";
import { useAuthStore } from "@/store/auth";
import {
  permissionSnapshot,
  sectionSnapshot,
} from "@/__tests__/fixtures/permission-snapshot";

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

vi.mock("@/components/v2/modals/DraftCompletionModal", () => ({
  DraftCompletionModal: (props: {
    open: boolean;
    contractor: { contract_id: number; candidate: { name: string } };
  }) =>
    props.open ? (
      <div role="dialog">
        uzupełnienie szkicu {props.contractor.contract_id} {props.contractor.candidate.name}
      </div>
    ) : null,
}));

vi.mock("@/components/contracts/ContractSidePanel", () => ({
  ContractSidePanel: (props: { contractId: number }) => (
    <div data-testid="contract-side-panel">panel {props.contractId}</div>
  ),
}));

type Row = {
  id: number;
  candidate_name: string;
  status: string;
  missing_fields: string[];
};

const member = (row: Row) => ({
  id: row.id,
  client_id: 1,
  client_name: "Bank Przykładowy",
  job_title: null,
  start_date: "2026-12-01",
  end_date: null,
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
  missing_fields: row.missing_fields,
  group_members: [member(row)],
});

const DRAFTS: Row[] = [
  { id: 701, candidate_name: "Ewa Szkicowa", status: "draft", missing_fields: ["start_date", "rate_client"] },
  { id: 702, candidate_name: "Olek Gotowy", status: "draft", missing_fields: [] },
  { id: 703, candidate_name: "Ida Stawkowa", status: "draft", missing_fields: ["rate_client"] },
];
const RUNNING: Row[] = [
  { id: 704, candidate_name: "Paweł Aktywny", status: "active", missing_fields: [] },
];
// Zbiór „Kończące się” liczy serwer: wypowiedziana + żywa z końcem w 30 dni.
const ENDING_BUCKET: Row[] = [
  { id: 705, candidate_name: "Jan Wypowiedziany", status: "ending", missing_fields: [] },
  { id: 706, candidate_name: "Ola Koniecmiesiąca", status: "active", missing_fields: [] },
];
const ALL = [...DRAFTS, ...RUNNING, ...ENDING_BUCKET];

type Params = { status?: string[]; bucket?: string };

function respond(params: Params) {
  const rows =
    params.bucket === "ending"
      ? ENDING_BUCKET
      : params.status
        ? ALL.filter((row) => params.status?.includes(row.status))
        : ALL;
  return {
    items: rows.map(toItem),
    total: rows.length,
    contractors_total: rows.length,
    contracts_total: rows.length,
    page: 1,
    page_size: 20,
  };
}

const contractCalls = () =>
  mocks.get.mock.calls
    .filter((call) => call[0] === "/api/contracts")
    .map((call) => (call[1]?.params ?? {}) as Record<string, unknown>);

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

function signIn(role: string, extra: Record<string, unknown> = {}) {
  useAuthStore.setState({
    user: {
      id: 9,
      email: `${role}@example.com`,
      name: role,
      role,
      roles: [role],
      profile_completed: true,
      profile_completed_at: null,
      force_password_change: false,
      force_password_change_at: null,
      capabilities: [],
      analytics_capabilities: [],
      ...extra,
    },
    realUser: null,
    hydrated: true,
  } as never);
}

const quickFilters = () => screen.getByRole("group", { name: "Szybkie filtry kontraktów" });
const pill = (label: string) =>
  within(quickFilters()).getByRole("button", { name: new RegExp(`^${label}`) });

describe("ContractsListV2 — jedna lista z szybkimi filtrami (18.11.2026)", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/contracts");
    window.sessionStorage.clear();
    signIn("admin", { capabilities: ["view_finance"], analytics_capabilities: ["view_finance"] });
    mocks.get.mockReset();
    mocks.get.mockImplementation((url: string, config?: { params?: Params }) => {
      if (url === "/api/contracts") {
        return Promise.resolve({ data: respond(config?.params ?? {}) });
      }
      return Promise.resolve({ data: [] });
    });
    mocks.stats.mockReset();
    mocks.stats.mockResolvedValue({
      data: { draft: 3, drafts_incomplete: 2, active: 3, active_contracts: 3, ending: 2 },
    });
  });

  afterEach(() => {
    useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
  });

  it("pigułki liczy serwer: statusy rejestru, a „Kończące się” przez bucket=ending", async () => {
    renderList();

    await waitFor(() => expect(pill("Kończące się")).toHaveTextContent("2"));
    expect(pill("Do uzupełnienia")).toHaveTextContent("3");
    expect(pill("Aktywne")).toHaveTextContent("3");
    expect(pill("Wszystkie")).toHaveTextContent("6");
    // Domyślny widok = obowiązujące dziś.
    expect(pill("Aktywne")).toHaveAttribute("aria-pressed", "true");

    expect(contractCalls()).toContainEqual(
      expect.objectContaining({ bucket: "ending", status: undefined, group_by_candidate: true }),
    );
    expect(contractCalls()).toContainEqual(
      expect.objectContaining({ status: ["draft", "ready_for_signature"], bucket: undefined }),
    );
  });

  it("„Kończące się” filtruje listę tym samym zbiorem co licznik, bez banera z datą końca", async () => {
    renderList();
    await screen.findByText("Paweł Aktywny");

    fireEvent.click(pill("Kończące się"));

    // Poprzednia strona zostaje do przyjścia nowej (keepPreviousData).
    await waitFor(() => expect(screen.queryByText("Paweł Aktywny")).not.toBeInTheDocument());
    expect(screen.getByText("Jan Wypowiedziany")).toBeInTheDocument();
    expect(screen.getByText("Ola Koniecmiesiąca")).toBeInTheDocument();
    expect(pill("Kończące się")).toHaveAttribute("aria-pressed", "true");
    expect(window.location.search).toBe("?status=all&ending=30");
    // Pigułka już mówi, co jest włączone — bez drugiego chipa w pasku filtrów.
    expect(screen.getAllByRole("button", { name: /^Kończące się/ })).toHaveLength(1);

    for (const params of contractCalls()) {
      expect(params).not.toHaveProperty("expiring_in_days");
    }
    expect(mocks.get.mock.calls.some((call) => call[0] === "/api/contracts/expiring")).toBe(false);
    expect(screen.queryByText(/w ciągu 30 dni/)).not.toBeInTheDocument();
  });

  it("stary link ?ending=30 zapala pigułkę „Kończące się”", async () => {
    window.history.replaceState({}, "", "/contracts?ending=30");
    renderList();

    expect(await screen.findByText("Jan Wypowiedziany")).toBeInTheDocument();
    expect(pill("Kończące się")).toHaveAttribute("aria-pressed", "true");
  });

  it("ostrzeżenie o szkicach prowadzi do „Do uzupełnienia”", async () => {
    renderList();

    const warning = await screen.findByText("2 szkice czekają na uzupełnienie");
    fireEvent.click(within(warning.closest("[role=status]") as HTMLElement).getByRole("button", { name: "Pokaż" }));

    await waitFor(() => expect(pill("Do uzupełnienia")).toHaveAttribute("aria-pressed", "true"));
    expect(screen.queryByText("2 szkice czekają na uzupełnienie")).not.toBeInTheDocument();
    expect(await screen.findByText("Ewa Szkicowa")).toBeInTheDocument();
  });

  it("wiersz szkicu ma „Uzupełnij · N braki” albo „Aktywuj”; klik otwiera okno, nie panel", async () => {
    window.history.replaceState({}, "", "/contracts?status=draft&status=ready_for_signature");
    renderList();

    const fill = await screen.findByRole("button", { name: "Uzupełnij · 2 braki" });
    expect(screen.getByRole("button", { name: "Uzupełnij · 1 brak" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aktywuj" })).toBeInTheDocument();

    fireEvent.click(fill);

    expect(await screen.findByRole("dialog")).toHaveTextContent("uzupełnienie szkicu 701 Ewa Szkicowa");
    expect(window.location.search).not.toContain("contract=");
    expect(screen.queryByTestId("contract-side-panel")).not.toBeInTheDocument();
  });

  it("aktywna umowa nie dostaje przycisku szkicu", async () => {
    renderList();
    await screen.findByText("Paweł Aktywny");

    expect(screen.queryByRole("button", { name: /^Uzupełnij/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aktywuj" })).not.toBeInTheDocument();
  });

  it("bez „Kontrakty i zamówienia: edycja” szkic pokazuje braki, ale bez przycisku", async () => {
    signIn("recruiter", {
      effective_action_access: permissionSnapshot("delivery_view"),
      effective_section_access: sectionSnapshot(["delivery_view"]),
    });
    window.history.replaceState({}, "", "/contracts?status=draft");
    renderList();
    await screen.findByText("Ewa Szkicowa");

    expect(screen.queryByRole("button", { name: /^Uzupełnij/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aktywuj" })).not.toBeInTheDocument();
    // Stawek ta osoba nie widzi — nie liczą się do braków (jak w dawnej „Obsłudze”).
    expect(screen.getByText("1 brak")).toBeInTheDocument();
    expect(screen.getByText("gotowy do aktywacji")).toBeInTheDocument();
    expect(screen.getByText("Czeka na uzupełnienie stawek")).toBeInTheDocument();
  });

  it("bez podglądu kwot szkic z samymi brakami stawek czeka na osobę od stawek", async () => {
    signIn("recruiter", {
      effective_action_access: permissionSnapshot("contracts_orders_edit"),
      effective_section_access: sectionSnapshot(["contracts_orders_edit"]),
    });
    window.history.replaceState({}, "", "/contracts?status=draft");
    renderList();
    await screen.findByText("Ida Stawkowa");

    // Ewie brakuje też daty startu, którą ta osoba uzupełni; Idzie — tylko stawki.
    expect(screen.getByRole("button", { name: "Uzupełnij · 1 brak" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Uzupełnij/ })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Aktywuj" })).toBeInTheDocument();
    expect(screen.getByText("Czeka na uzupełnienie stawek")).toHaveAttribute(
      "title",
      expect.stringContaining("Stawki uzupełnia osoba z uprawnieniem"),
    );
  });
});

describe("draftRowAction — stan szkicu w wierszu", () => {
  const all = { canSeeRates: true, canEditRates: true };
  const none = { canSeeRates: false, canEditRates: false };

  it("komplet danych = „Aktywuj”", () => {
    expect(draftRowAction([], none)).toEqual({ kind: "activate" });
  });

  it("liczy braki widoczne dla konta", () => {
    expect(draftRowAction(["start_date", "rate_client"], all)).toEqual({ kind: "complete", missing: 2 });
    expect(draftRowAction(["start_date", "rate_client"], none)).toEqual({ kind: "complete", missing: 1 });
  });

  it("same stawki bez prawa do ich zmiany czekają na osobę od stawek", () => {
    expect(draftRowAction(["rate_client", "rate_candidate"], none)).toEqual({ kind: "waits-for-rates" });
    // Kto stawki widzi, ten je uzupełnia (okno pokaże pola).
    expect(draftRowAction(["rate_client"], { canSeeRates: true, canEditRates: false })).toEqual({
      kind: "complete",
      missing: 1,
    });
  });

  it("polska liczba mnoga braków", () => {
    expect(["1", "2", "4", "5", "12", "22"].map((n) => missingCountLabel(Number(n)))).toEqual([
      "1 brak",
      "2 braki",
      "4 braki",
      "5 braków",
      "12 braków",
      "22 braki",
    ]);
  });
});
