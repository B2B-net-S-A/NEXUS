import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import {
  ContractorOrderPanel,
  type ContractorOrderFocus,
} from "@/components/client-profile/orders/ContractorOrderPanel";
import type { ClientOrderRead, ContractWithOrdersRead } from "@/lib/api/dlPortal";
import { canViewClientFinance, useAuthStore } from "@/store/auth";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const authState = vi.hoisted(() => ({
  role: "admin" as string,
  capabilities: ["manage_finance"] as string[],
}));
// „Podgląd jako" (impersonacja) — `realUser !== null` chowa „Zakończ współpracę".
const impersonation = vi.hoisted(() => ({ realUser: null as null | { role: string } }));

vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (s: {
      user: { role: string; capabilities: string[] };
      realUser: null | { role: string };
    }) => unknown,
  ) => selector({ user: authState, realUser: impersonation.realUser }),
  // Lustro `canManageContractStatus` ze store/auth.ts (bez sekcji — w testach
  // każda rola ma dostęp do Delivery).
  canManageContractStatus: (user: { role?: string } | null) =>
    ["admin", "delivery_lead", "talent_community_manager"].includes(user?.role ?? ""),
  canManageCandidateFinance: (
    user: { role?: string; capabilities?: string[] } | null,
  ) =>
    user?.role === "admin" &&
    (user.capabilities ?? []).includes("manage_finance"),
  canViewClientFinance: (
    user: { role?: string; capabilities?: string[] } | null,
    _clientId: number,
  ) =>
    user?.role === "admin" ||
    (user?.role === "finance" &&
      (user.capabilities ?? []).includes("view_finance")),
}));

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    listContractorsWithOrders: vi.fn(),
    updateOrder: vi.fn(),
    deleteOrder: vi.fn(),
    // Dialog usuwania pyta serwer, CO zniknie razem z zamówieniem — bez tego
    // przycisk „Usuń” zostaje wyłączony (patrz `DeleteOrderDialog`).
    previewOrderDeletion: vi.fn().mockResolvedValue({
      data: {
        order_id: 61,
        order_number: "61",
        status: "active",
        is_group_line: false,
        deletes_row: true,
        blocked_by: [],
        has_file: false,
        rate_changes: [],
        currency: "PLN",
        rate_unit: "hourly",
        amounts_redacted: false,
      },
    }),
    closeOrder: vi.fn(),
    dismissDraftCard: vi.fn(),
    createOrderExtension: vi.fn(),
    extractOrderPdf: vi.fn(),
    replaceOrderPo: vi.fn(),
    // Domyślna jednostka klienta (nigdy `monthly`) — formularze inicjują nią
    // pole „jednostka stawki" zamiast twardego `monthly`.
    getDefaultRateUnit: vi.fn().mockResolvedValue({ data: { rate_unit: "hourly" } }),
  },
}));

const fileMocks = vi.hoisted(() => ({
  download: vi.fn(),
  open: vi.fn(),
}));
vi.mock("@/lib/authenticated-files", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/authenticated-files")>();
  return {
    ...actual,
    downloadAuthenticatedFile: (...args: unknown[]) => fileMocks.download(...args),
    openAuthenticatedFile: (...args: unknown[]) => fileMocks.open(...args),
  };
});

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    contractsApi: { ...actual.contractsApi, update: vi.fn() },
  };
});

// Struktura umów e-Zdrowia: hook `useExecutiveContractOptions` pyta o nią
// wyłącznie u klienta 115. Podmieniamy metodę obiektu API — hooki i czyste
// funkcje (`executiveContractOptionGroups`) zostają prawdziwe.
const executiveContractMocks = vi.hoisted(() => ({
  // Domyślnie pusta struktura — testy spoza bloku e-Zdrowia nie zasiewają jej,
  // a `undefined` z queryFn react-query traktuje jako błąd zapytania.
  structure: vi.fn().mockResolvedValue({ framework_contracts: [] }),
}));
vi.mock("@/lib/api/executiveContracts", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/executiveContracts")>();
  Object.assign(actual.executiveContractsApi, {
    structure: (...args: unknown[]) => executiveContractMocks.structure(...args),
  });
  return { ...actual };
});

import { contractsApi } from "@/lib/api";
import { dlPortalApi } from "@/lib/api/dlPortal";
import { EZDROWIE_CLIENT_ID } from "@/lib/ezdrowie";

// ── Fixtures ──────────────────────────────────────────────────────────────────

/** Local YYYY-MM-DD offset from today, matching the component's todayLocalISO. */
function localISO(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function makeOrder(partial: Partial<ClientOrderRead> & { id: number; title: string }): ClientOrderRead {
  return {
    client_id: 7,
    contract_id: 529,
    job_id: null,
    framework_contract_id: null,
    description: null,
    status: "active",
    start_date: null,
    end_date: null,
    rate_client: null,
    total_value: null,
    currency: "PLN",
    project_part: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    created_by_user_id: null,
    notes: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    candidate_id: 99,
    candidate_name: "Tomasz Sadowski",
    contract_status: "active",
    job_title: null,
    monthly_margin: null,
    days_to_end: null,
    ...partial,
  };
}

const ACTIVE = makeOrder({
  id: 1,
  title: "45767",
  order_type: "md",
  start_date: localISO(-30),
  end_date: null,
  rate_client: 180,
});
const FUTURE = makeOrder({
  id: 2,
  title: "3320",
  order_type: "cost",
  start_date: localISO(30),
  end_date: localISO(60),
  rate_client: 190,
});
const HISTORY = makeOrder({
  id: 3,
  title: "OLD-1",
  order_type: "periodic",
  status: "completed",
  start_date: localISO(-400),
  end_date: localISO(-40),
  rate_client: 150,
  // Ticket #4: etykieta "Job: …" ma NIE renderować się mimo obecnej wartości.
  job_title: "Specjalista: Engineer DevOps",
});

// Backend returns orders sorted by start_date desc.
const CONTRACTOR = {
  contract_id: 529,
  candidate_id: 99,
  candidate_name: "Tomasz Sadowski",
  contract_status: "active",
  contract_start_date: localISO(-30),
  contract_end_date: null,
  rate_candidate: 120,
  rate_client_currency: "PLN",
  rate_candidate_currency: "PLN",
  rate_unit: "monthly",
  initial_job_id: null,
  initial_job_title: "Specjalista: Engineer DevOps",
  latest_order_id: 2,
  latest_order_end_date: FUTURE.end_date,
  latest_order_rate_client: 190,
  latest_order_monthly_margin: 70,
  days_to_latest_end: 60,
  orders: [FUTURE, ACTIVE, HISTORY],
};

interface RenderPanelOptions {
  suggestedOrderType?: "periodic" | "cost" | "md";
  legacyNullOrderType?: "periodic" | "md";
  searching?: boolean;
  queryClient?: QueryClient;
}

/**
 * Lustro tego, jak lista zamówień zasila panel: te same dane z
 * `listContractorsWithOrders` i te same bramki (`can_manage_finance` z serwera,
 * widoczność kwot z `canViewClientFinance`). Jeden panel na kontraktora.
 */
function PanelHarness({
  clientId,
  suggestedOrderType,
  legacyNullOrderType,
  searching,
}: {
  clientId: number;
  suggestedOrderType: "periodic" | "cost" | "md";
  legacyNullOrderType: "periodic" | "md";
  searching: boolean;
}) {
  const user = useAuthStore((state) => state.user);
  const { data } = useQuery({
    queryKey: ["dl-orders-grouped", clientId],
    queryFn: async () => (await dlPortalApi.listContractorsWithOrders(clientId)).data,
  });
  if (!data) return null;
  const canManageFinance = data.can_manage_finance ?? false;
  const canViewFinance = canManageFinance || canViewClientFinance(user, clientId);
  return (
    <>
      {data.contractors.map((contractor: ContractWithOrdersRead) => (
        <ContractorOrderPanel
          key={contractor.contract_id}
          contractor={contractor}
          clientId={clientId}
          canManageOrders={canManageFinance}
          canManageFinance={canManageFinance}
          canViewFinance={canViewFinance}
          suggestedOrderType={suggestedOrderType}
          legacyNullOrderType={legacyNullOrderType}
          searching={searching}
          onClose={() => undefined}
        />
      ))}
    </>
  );
}

/** „Usuń zamówienie" przy bieżącym zamówieniu stoi w menu „⋯" stopki panelu. */
async function openDeleteFromMenu() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Więcej akcji zamówienia" }));
  await user.click(await screen.findByRole("menuitem", { name: /Usuń zamówienie/ }));
}

function renderPanel(clientId = 7, options: RenderPanelOptions = {}) {
  const queryClient =
    options.queryClient ??
    new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <PanelHarness
          clientId={clientId}
          suggestedOrderType={options.suggestedOrderType ?? "periodic"}
          legacyNullOrderType={options.legacyNullOrderType ?? "periodic"}
          searching={options.searching ?? false}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  impersonation.realUser = null;
  authState.role = "admin";
  authState.capabilities = ["manage_finance"];
  vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
    data: {
      contractors: [structuredClone(CONTRACTOR)],
      total_contractors: 1,
      // Bramka finansowa liczona jest teraz SERWEROWO per klient (admin albo
      // przypisany Delivery Lead) — front nie zna przypisań DL, więc czyta
      // flagę z odpowiedzi zamiast zgadywać po roli.
      can_manage_finance: true,
    },
  } as never);
  vi.mocked(dlPortalApi.updateOrder).mockResolvedValue({ data: {} } as never);
  vi.mocked(dlPortalApi.deleteOrder).mockResolvedValue({ data: {} } as never);
  vi.mocked(dlPortalApi.createOrderExtension).mockResolvedValue({
    data: { id: 4242 },
  } as never);
  vi.mocked(contractsApi.update).mockResolvedValue({ data: {} } as never);
});

// ── Pure split logic ──────────────────────────────────────────────────────────

describe("ContractorOrderPanel card", () => {
  it("oznacza typ bieżącego, przyszłego i historycznego zamówienia", async () => {
    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByText("MD")).toBeInTheDocument();
    expect(screen.getByText("Kosztowe")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Historia zamówień \(1\)/ }),
    );
    expect(screen.getByText("Okresowe")).toBeInTheDocument();
  });

  it("oznacza kartę z wyłącznie anulowanym orderem jego ostatnim typem", async () => {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          {
            ...structuredClone(CONTRACTOR),
            contract_id: 601,
            candidate_name: "Anulowane kosztowe",
            contract_status: "ended",
            orders: [
              makeOrder({
                id: 601,
                title: "CANCELLED-COST",
                contract_id: 601,
                status: "cancelled",
                order_type: "cost",
                start_date: localISO(-20),
              }),
            ],
          },
          {
            ...structuredClone(CONTRACTOR),
            contract_id: 602,
            candidate_name: "Anulowane MD",
            contract_status: "ended",
            orders: [
              makeOrder({
                id: 602,
                title: "CANCELLED-MD",
                contract_id: 602,
                status: "cancelled",
                order_type: "md",
                start_date: localISO(-10),
              }),
            ],
          },
        ],
        total_contractors: 2,
        can_manage_finance: true,
      },
    } as never);

    renderPanel();

    await screen.findByRole("heading", { name: /Anulowane kosztowe/ });
    expect(screen.getByText("Kosztowe")).toBeInTheDocument();
    expect(screen.getByText("MD")).toBeInTheDocument();
    expect(screen.queryByText("Okresowe")).not.toBeInTheDocument();
  });

  it("oznacza legacy NULL jako MD w każdym slocie klienta bez periodic", async () => {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          {
            ...structuredClone(CONTRACTOR),
            orders: [FUTURE, ACTIVE, HISTORY].map((order) => ({
              ...structuredClone(order),
              order_type: null,
            })),
          },
        ],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    const user = userEvent.setup();

    renderPanel(7, { suggestedOrderType: "cost", legacyNullOrderType: "md" });

    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getAllByText("MD")).toHaveLength(2);
    expect(screen.queryByText("Kosztowe")).not.toBeInTheDocument();
    expect(screen.queryByText("Okresowe")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Historia zamówień \(1\)/ }),
    );
    expect(screen.getAllByText("MD")).toHaveLength(3);

    await user.click(
      screen.getAllByRole("button", { name: "Uzupełnij zamówienie" })[0],
    );
    expect(await screen.findByLabelText(/Budżet w MD/)).toBeInTheDocument();
  });

  it('mówi „Brak aktywnego zamówienia", gdy okres minął, a umowa trwa', async () => {
    // Reguła zakładki „Zakończeni" (09.2026): upływ okresu zamówienia nie
    // przenosi osoby do „Zakończonych" — zostaje w „Aktywnych" z dopiskiem.
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [{ ...structuredClone(CONTRACTOR), orders: [HISTORY], days_to_latest_end: -40 }],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    renderPanel();
    expect(await screen.findByTestId("no-active-order-note")).toHaveTextContent(
      "Brak aktywnego zamówienia",
    );
  });

  it('nie dopisuje „Brak aktywnego zamówienia", gdy zamówienie trwa albo dopiero się zacznie', async () => {
    renderPanel();
    expect((await screen.findAllByText(/Tomasz Sadowski/)).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("no-active-order-note")).toBeNull();
  });

  it("shows the consultant name with the contract id and recruitment origin", async () => {
    renderPanel();
    expect(
      await screen.findByRole("heading", { name: /Tomasz Sadowski/ }),
    ).toBeInTheDocument();
    // Active order title surfaces as "Numer zamówienia" at the top of the card.
    expect(screen.getByText("45767")).toBeInTheDocument();
    // Numer kontraktu obok nazwiska — BEZ dopisku statusu („draft").
    expect(screen.getByText("Kontrakt #529")).toBeInTheDocument();
    expect(screen.queryByText(/Kontrakt #529 draft/)).not.toBeInTheDocument();
    // Rekrutacja, z której wyszedł kontraktor.
    expect(screen.getByText(/z rekrutacji/i)).toBeInTheDocument();
    expect(
      screen.getByText("Specjalista: Engineer DevOps"),
    ).toBeInTheDocument();
  });

  it("nazwisko w nagłówku kafelka prowadzi do kontraktu z tego wiersza", async () => {
    // Osoba pracująca u kilku klientów ma kilka kontraktów — kafelek zna ten
    // jeden, który dotyczy klienta, z którego profilu się w niego kliknęło.
    renderPanel();
    const heading = await screen.findByRole("heading", {
      name: /Tomasz Sadowski/,
    });

    expect(
      within(heading).getByRole("link", { name: "Tomasz Sadowski" }),
    ).toHaveAttribute("href", "/contracts/529");
    // Numer obok zostaje zwykłym tekstem — drugi link do tego samego celu to
    // zbędny przystanek w nawigacji klawiaturą.
    expect(
      screen.queryByRole("link", { name: "Kontrakt #529" }),
    ).not.toBeInTheDocument();
  });

  it("wiersz przyszłego zamówienia nie powtarza nazwiska — panel dotyczy jednej osoby", async () => {
    renderPanel();
    await screen.findByText(/Przyszłe zamówienie \(1\)/);

    const links = screen
      .getAllByRole("link", { name: "Tomasz Sadowski" })
      .map((link) => link.getAttribute("href"));
    expect(links).toEqual(["/contracts/529"]);
  });

  it("trzyma numer, każdą stawkę i okres w osobnych, stałych liniach", async () => {
    // Regresja układu z ticketu: długość tekstu nie może decydować, czy okres
    // sklei się ze stawkami. W panelu każde pole ma własny wiersz faktów.
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    const numberRow = screen
      .getByTitle("Numer zamówienia")
      .closest('[data-order-detail-line="number"]');
    const costRow = screen
      .getByTitle("Stawka kosztowa")
      .closest('[data-order-detail-line="cost"]');
    const revenueRow = screen
      .getByTitle("Stawka przychodowa")
      .closest('[data-order-detail-line="revenue"]');
    const periodRow = screen
      .getByTitle("Okres zamówienia")
      .closest('[data-order-detail-line="period"]');

    expect(numberRow).not.toBeNull();
    expect(costRow).not.toBeNull();
    expect(revenueRow).not.toBeNull();
    expect(periodRow).not.toBeNull();
    expect(new Set([numberRow, costRow, revenueRow, periodRow]).size).toBe(4);

    expect(
      screen
        .getByRole("button", { name: "Edytuj: Numer zamówienia" })
        .closest("[data-order-detail-line]"),
    ).toBe(numberRow);
    // Stawka kosztowa pochodzi z kontraktu (09.2026) — w miejscu przycisku
    // edycji jest znacznik źródła, w tej samej linii.
    expect(
      screen.getByText("(z kontraktu)").closest("[data-order-detail-line]"),
    ).toBe(costRow);
    expect(
      screen
        .getByRole("button", { name: "Edytuj: Stawka przychodowa" })
        .closest("[data-order-detail-line]"),
    ).toBe(revenueRow);
    expect(
      screen
        .getByRole("button", { name: "Edytuj: okres zamówienia" })
        .closest("[data-order-detail-line]"),
    ).toBe(periodRow);
  });

  it("renames the section to Przyszłe zamówienie and lists the future order", async () => {
    renderPanel();
    expect(await screen.findByText(/Przyszłe zamówienie \(1\)/)).toBeInTheDocument();
    // Future entry: candidate name + "Numer zamówienia: <title>", no draft badge.
    expect(screen.getByText("Numer zamówienia:")).toBeInTheDocument();
    expect(screen.getByText("3320")).toBeInTheDocument();
  });

  it.each(["tac", "delivery_lead"])(
    "hides candidate finance rows when the server says %s cannot manage them",
    async (role) => {
      // Bramka jest teraz SERWEROWA (`can_manage_finance` w odpowiedzi), bo
      // front nie zna przypisań Delivery Leada. Test steruje flagą, nie rolą —
      // inaczej sprawdzałby zgadywanie po roli, którego już nie ma.
      authState.role = role;
      vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
        data: {
          contractors: [structuredClone(CONTRACTOR)],
          total_contractors: 1,
          can_manage_finance: false,
        },
      } as never);
      renderPanel();
      await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
      // Kotwica na `title`, nie na widocznej etykiecie: kafelek skraca ją do
      // „koszt."/„przych.", żeby obie stawki mieściły się w jednej linii, a
      // kontrakt, którego pilnuje ten test, dotyczy WIDOCZNOŚCI pola, nie
      // jego brzmienia.
      expect(screen.queryByTitle("Stawka kosztowa")).not.toBeInTheDocument();
      expect(screen.queryByTitle("Stawka przychodowa")).not.toBeInTheDocument();
      // Period is not finance-gated — it stays visible.
      expect(screen.getByTitle("Okres zamówienia")).toBeInTheDocument();
    },
  );

  it("Finance widzi pełne stawki, ale bez „Zakończ współpracę” (bramka roli jak na stronie kontraktu)", async () => {
    authState.role = "finance";
    authState.capabilities = ["view_finance"];
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [structuredClone(CONTRACTOR)],
        total_contractors: 1,
        can_manage_finance: false,
      },
    } as never);
    const user = userEvent.setup();

    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    expect(screen.getByTitle("Stawka kosztowa")).toBeInTheDocument();
    expect(screen.getByTitle("Stawka przychodowa")).toBeInTheDocument();
    expect(screen.queryAllByLabelText(/^Edytuj:/)).toHaveLength(0);
    expect(
      screen.queryByRole("button", { name: "Uzupełnij zamówienie" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Dodaj przedłużenie/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByTitle("Usuń zamówienie")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Więcej akcji zamówienia" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Zakończ współpracę/ }),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Historia zamówień \(1\)/ }),
    );
    expect(await screen.findByText(/przychód 150/)).toBeInTheDocument();
    expect(screen.queryByTitle("Usuń zamówienie")).not.toBeInTheDocument();
  });

  it("TAC widzi dane, ale żadnej mutacji zamówienia ani „Zakończ współpracę”", async () => {
    authState.role = "tac";
    authState.capabilities = [];
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [structuredClone(CONTRACTOR)],
        total_contractors: 1,
        can_manage_finance: false,
      },
    } as never);
    const user = userEvent.setup();

    renderPanel(EZDROWIE_CLIENT_ID);
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    expect(screen.queryAllByLabelText(/^Edytuj:/)).toHaveLength(0);
    expect(screen.getByLabelText("Umowa wykonawcza")).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Uzupełnij zamówienie" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Dodaj przedłużenie/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByTitle("Usuń zamówienie")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Więcej akcji zamówienia" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Zakończ współpracę/ }),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Historia zamówień \(1\)/ }),
    );
    expect(await screen.findByText("OLD-1")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Uzupełnij zamówienie" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByTitle("Usuń zamówienie")).not.toBeInTheDocument();
  });

  it("shows candidate finance rows when the server grants manage_finance", async () => {
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getByTitle("Stawka kosztowa")).toBeInTheDocument();
    expect(screen.getByTitle("Stawka przychodowa")).toBeInTheDocument();
  });

  it("shows finance rows to an assigned Delivery Lead", async () => {
    // Sedno poszerzenia uprawnień: rola sama w sobie niczego nie otwiera ani
    // nie zamyka — decyduje flaga policzona serwerowo dla TEGO klienta.
    authState.role = "delivery_lead";
    authState.capabilities = [];
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getByTitle("Stawka kosztowa")).toBeInTheDocument();
    expect(screen.getByTitle("Stawka przychodowa")).toBeInTheDocument();
  });

  it("reveals history behind the toggle", async () => {
    const user = userEvent.setup();
    renderPanel();
    const toggle = await screen.findByRole("button", {
      name: /Historia zamówień \(1\)/,
    });
    expect(screen.queryByText("OLD-1")).not.toBeInTheDocument();
    await user.click(toggle);
    expect(await screen.findByText("OLD-1")).toBeInTheDocument();
    // Ticket #4: etykieta "Job: <rekrutacja>" usunięta z wierszy historii.
    expect(screen.queryByText(/Job:/)).not.toBeInTheDocument();
  });

  it("saves an edited order number via updateOrder", async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    await user.click(screen.getByLabelText("Edytuj: Numer zamówienia"));
    const input = screen.getByLabelText("Numer zamówienia");
    await user.clear(input);
    await user.type(input, "99999");
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(dlPortalApi.updateOrder).toHaveBeenCalledWith(7, ACTIVE.id, {
        title: "99999",
      }),
    );
  });

  it("zapis na karcie kontraktora odświeża też kafle profilu i alerty DL (R10-N15-6)", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    renderPanel(7, { queryClient });
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    await user.click(screen.getByLabelText("Edytuj: Numer zamówienia"));
    const input = screen.getByLabelText("Numer zamówienia");
    await user.clear(input);
    await user.type(input, "99999");
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ queryKey: ["client-profile", 7] }),
    );
    expect(spy).toHaveBeenCalledWith({ queryKey: ["dl-alerts"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["order-group-events", 7] });
  });

  it("keeps the cost rate read-only when the contract carries it", async () => {
    // Kontrakt jest źródłem prawdy dla stawki kosztowej (09.2026): zapis
    // w zamówieniu i tak nadpisałaby synchronizacja, więc pola nie da się
    // edytować, a karta mówi, skąd liczba pochodzi.
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.queryByLabelText("Edytuj: Stawka kosztowa")).not.toBeInTheDocument();
    expect(screen.getByText("(z kontraktu)")).toBeInTheDocument();
  });

  it("saves an edited stawka kosztowa via the orders endpoint", async () => {
    // Edycja zostaje wyłącznie dla kontraktu BEZ stawki kosztowej.
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [{ ...structuredClone(CONTRACTOR), rate_candidate: null }],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    const user = userEvent.setup();
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    await user.click(screen.getByLabelText("Edytuj: Stawka kosztowa"));
    const input = screen.getByLabelText("Stawka kosztowa");
    await user.clear(input);
    await user.type(input, "12500");
    await user.keyboard("{Enter}");

    await waitFor(() =>
      // PATCH /api/contracts/{id} zachowuje własną, admin-only bramkę na 17
      // pól finansowych, więc przypisany DL dostawał tam 403. Stawka kosztowa
      // idzie teraz tą samą ścieżką co reszta zamówienia.
      expect(dlPortalApi.updateOrder).toHaveBeenCalledWith(7, 1, {
        rate_candidate: 12500,
      }),
    );
  });

  it("saves the edited future order number against the future order id", async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByText("3320");

    await user.click(screen.getByLabelText("Edytuj: Numer zamówienia (przyszłe)"));
    const input = screen.getByLabelText("Numer zamówienia (przyszłe)");
    await user.clear(input);
    await user.type(input, "3321");
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(dlPortalApi.updateOrder).toHaveBeenCalledWith(7, FUTURE.id, {
        title: "3321",
      }),
    );
  });

  it("saves an edited okres (start + end) via updateOrder", async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    await user.click(screen.getByLabelText("Edytuj: okres zamówienia"));
    const endInput = screen.getByLabelText("Data do (puste = bezterminowo)");
    await user.clear(endInput);
    await user.type(endInput, "2027-03-31");
    await user.click(screen.getByLabelText("Zapisz"));

    await waitFor(() =>
      expect(dlPortalApi.updateOrder).toHaveBeenCalledWith(7, ACTIVE.id, {
        start_date: ACTIVE.start_date,
        end_date: "2027-03-31",
      }),
    );
  });

  it("shows a placeholder (not —/mc) when a rate is null", async () => {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [{ ...structuredClone(CONTRACTOR), rate_candidate: null }],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getByText("ustaw stawkę")).toBeInTheDocument();
  });

  it("uses the active order's unit and currency before contract fallbacks", async () => {
    const contractor = structuredClone(CONTRACTOR);
    const active = contractor.orders.find((order) => order.id === ACTIVE.id)!;
    active.rate_unit = "hourly";
    active.currency = "GBP";
    active.rate_client_currency = "EUR";
    active.rate_candidate_currency = "USD";
    active.rate_candidate = 125;
    const history = contractor.orders.find((order) => order.id === HISTORY.id)!;
    history.rate_unit = "daily";
    history.rate_client_currency = "USD";
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [contractor],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getByText("125 USD/h")).toBeInTheDocument();
    expect(screen.getByText("180 EUR/h")).toBeInTheDocument();
    expect(screen.queryByText("120 PLN/mc")).not.toBeInTheDocument();
    await userEvent.setup().click(
      screen.getByRole("button", { name: /Historia zamówień \(1\)/ }),
    );
    expect(screen.getByText(/przychód 150 USD\/MD/)).toBeInTheDocument();
  });

  it("falls back to the contract unit/currency for historical orders", async () => {
    const contractor = {
      ...structuredClone(CONTRACTOR),
      rate_unit: "daily",
      rate_client_currency: "GBP",
      rate_candidate_currency: "USD",
    };
    const active = contractor.orders.find((order) => order.id === ACTIVE.id)!;
    delete active.rate_unit;
    active.currency = null;
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [contractor],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);

    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getByText("120 USD/MD")).toBeInTheDocument();
    expect(screen.getByText("180 GBP/MD")).toBeInTheDocument();
  });
});

// ── Search ────────────────────────────────────────────────────────────────────

describe("ContractorOrderPanel — wyszukiwanie", () => {
  it("aktywne wyszukiwanie wymusza rozwiniętą historię (trafienie w starym numerze)", async () => {
    renderPanel(7, { searching: true });
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(await screen.findByText("OLD-1")).toBeInTheDocument();
    // Przełącznik nie może schować dopasowanego zamówienia.
    fireEvent.click(screen.getByRole("button", { name: /Historia zamówień \(1\)/ }));
    expect(screen.getByText("OLD-1")).toBeInTheDocument();
  });

  it("bez wyszukiwania historia jest domyślnie zwinięta", async () => {
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.queryByText("OLD-1")).not.toBeInTheDocument();
  });
});

describe("ContractorOrderPanel — plakietka przyszłego zamówienia", () => {
  it("zamówienie z dodanym przyszłym zamówieniem nie ostrzega; ostrzega przyszłe, które samo się kończy", async () => {
    // Ticket 09.2026 (kontrakt #145): 282129 kończy się za 8 dni, ale ma już
    // dodane przyszłe zamówienie 286699 (szkic). Nie wymaga działania.
    const continued = {
      ...structuredClone(CONTRACTOR),
      contract_id: 145,
      candidate_name: "Marek Urbański",
      days_to_latest_end: 69,
      orders: [
        makeOrder({
          id: 654,
          title: "286699",
          status: "draft",
          start_date: localISO(9),
          end_date: localISO(69),
        }),
        makeOrder({
          id: 308,
          title: "282129",
          status: "active",
          start_date: localISO(-176),
          end_date: localISO(8),
        }),
      ],
    };
    // Przyszłe zamówienie, które samo kończy się w oknie — to ono ostrzega.
    const futureEnding = {
      ...structuredClone(CONTRACTOR),
      contract_id: 146,
      candidate_name: "Jan Następca",
      orders: [
        makeOrder({
          id: 656,
          title: "NEXT-1",
          status: "active",
          start_date: localISO(9),
          end_date: localISO(22),
        }),
        makeOrder({
          id: 655,
          title: "CUR-1",
          status: "active",
          start_date: localISO(-100),
          end_date: localISO(8),
        }),
      ],
    };
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [continued, futureEnding],
        total_contractors: 2,
        can_manage_finance: true,
      },
    } as never);

    renderPanel();

    await screen.findByRole("heading", { name: /Jan Następca/ });
    const badges = screen.getAllByTestId("order-ending-badge");
    expect(badges).toHaveLength(1);
    expect(badges[0]).toHaveTextContent(
      "przyszłe zamówienie NEXT-1 kończy się za 22 dni",
    );
  });
});

describe("ContractorOrderPanel — kontraktor bez zamówienia", () => {
  // Realny przypadek z Banku Pocztowego: kontrakt istnieje, ale nie ma ani
  // jednego `ClientOrder`, więc i stawki są puste.
  const NO_ORDERS = {
    ...structuredClone(CONTRACTOR),
    contract_id: 701,
    candidate_name: "Bez Zamowien",
    rate_candidate: null,
    latest_order_rate_client: null,
    orders: [],
  };

  beforeEach(() => {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [NO_ORDERS],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
  });

  it("stawka przychodowa NIE znika, gdy nie ma jeszcze zamówienia", async () => {
    // Przed poprawką to pole wisiało na `activeOrder` i po prostu nie
    // renderowało się — karta pokazywała stawkę kosztową bez przychodowej
    // i wyglądała, jakby ta druga u tego klienta nie istniała.
    renderPanel();
    expect(
      await screen.findByRole("button", { name: /Edytuj: Stawka przychodowa/i }),
    ).toBeInTheDocument();
  });

  it("pusta karta pokazuje badge sugerowanego typu sekcji", async () => {
    renderPanel(7, { suggestedOrderType: "md" });
    expect(await screen.findByText("MD")).toBeInTheDocument();
  });

  it("okres i numer zamówienia są edytowalne mimo braku zamówienia", async () => {
    renderPanel();
    expect(
      await screen.findByRole("button", { name: /Edytuj: Numer zamówienia/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Edytuj: okres zamówienia/i }),
    ).toBeInTheDocument();
  });

  it("pierwszy zapis zakłada SZKIC zamówienia zamiast rzucać błędem", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      await screen.findByRole("button", { name: /Edytuj: Numer zamówienia/i }),
    );
    await user.type(screen.getByLabelText("Numer zamówienia"), "45767");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );
    const [, form] = vi.mocked(dlPortalApi.createOrderExtension).mock.calls[0];
    expect((form as FormData).get("title")).toBe("45767");
    // `draft`, nie `active`: zamówienie powstaje z jednego wpisanego pola,
    // więc trafia do pigułki „Draft (do uzupełnienia)".
    expect((form as FormData).get("order_status")).toBe("draft");
    expect((form as FormData).get("contract_id")).toBe("701");
  });

  it("„Uzupełnij zamówienie” renderuje się mimo braku zamówienia", async () => {
    // Regresja ticketu: przycisk wisiał na `activeOrder &&`, więc widzieli go
    // wyłącznie klienci z zaimportowanymi zamówieniami. Reszta dostawała samo
    // „Dodaj przedłużenie" i zgłaszała to jako funkcję włączoną wybranym
    // klientom — a to była różnica DANYCH, nie konfiguracji.
    renderPanel();
    expect(
      await screen.findByRole("button", { name: "Uzupełnij zamówienie" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Dodaj przedłużenie/i }),
    ).toBeInTheDocument();
  });

  it("anulowanie dialogu NIE zakłada szkicu", async () => {
    // Szkic powstaje dopiero przy zapisie. Tworzenie go w chwili otwarcia
    // zostawiałoby po każdym rozmyśleniu się wiersz „(bez numeru)", który
    // potem dopominałby się w pigułce „Draft (do uzupełnienia)".
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      await screen.findByRole("button", { name: "Uzupełnij zamówienie" }),
    );
    // Komunikat walidacji siedzi WEWNĄTRZ <label>, więc nazwa dostępna pola to
    // „Numer zamówieniaNumer zamówienia jest wymagany." — kotwiczymy na początku.
    await user.type(await screen.findByLabelText(/^Numer zamówienia/), "45767");
    await user.click(screen.getByRole("button", { name: "Anuluj" }));

    expect(dlPortalApi.createOrderExtension).not.toHaveBeenCalled();
    expect(dlPortalApi.updateOrder).not.toHaveBeenCalled();
  });

  it("zapis z dialogu zakłada zamówienie JEDNYM żądaniem z kompletem pól", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      await screen.findByRole("button", { name: "Uzupełnij zamówienie" }),
    );
    // Komunikat walidacji siedzi WEWNĄTRZ <label>, więc nazwa dostępna pola to
    // „Numer zamówieniaNumer zamówienia jest wymagany." — kotwiczymy na początku.
    await user.type(await screen.findByLabelText(/^Numer zamówienia/), "45767");
    await user.type(screen.getByLabelText("Data od"), "2026-09-01");
    await user.type(screen.getByLabelText("Data do"), "2027-02-28");
    await user.type(screen.getByLabelText("Stawka kosztowa"), "120");
    await user.type(screen.getByLabelText("Stawka przychodowa"), "180");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );
    const [, form] = vi.mocked(dlPortalApi.createOrderExtension).mock.calls[0];
    const sent = form as FormData;
    expect(sent.get("title")).toBe("45767");
    expect(sent.get("contract_id")).toBe("701");
    expect(sent.get("start_date")).toBe("2026-09-01");
    expect(sent.get("end_date")).toBe("2027-02-28");
    expect(sent.get("rate_candidate")).toBe("120");
    expect(sent.get("rate_client")).toBe("180");
    // „Uzupełnij zamówienie" DZIEDZICZY jednostkę kontraktu (tu fixture ma
    // `monthly`); domyślną jednostkę klienta stosuje wyłącznie tworzenie NOWEGO
    // kontraktora (`contract-with-order`), nie ta ścieżka uzupełniania.
    expect(sent.get("rate_unit")).toBe("monthly");
    expect(sent.get("rate_client_currency")).toBe("PLN");
    expect(sent.get("rate_candidate_currency")).toBe("PLN");
    expect(sent.has("currency")).toBe(false);
    // Status zostaje `draft` — o promocji decyduje serwer
    // (`_activate_complete_draft`), nie ten formularz.
    expect(sent.get("order_status")).toBe("draft");
    // Obie stawki powstają atomowo w POST — bez okna, w którym materializacja
    // grupy widziałaby stary koszt przed późniejszym PATCH-em.
    expect(dlPortalApi.updateOrder).not.toHaveBeenCalled();
  });

  it("nieudany atomowy POST można ponowić bez PATCH-a do nieistniejącego szkicu", async () => {
    const user = userEvent.setup();
    vi.mocked(dlPortalApi.createOrderExtension).mockRejectedValueOnce(
      new Error("boom"),
    );
    renderPanel();

    await user.click(
      await screen.findByRole("button", { name: "Uzupełnij zamówienie" }),
    );
    await user.type(await screen.findByLabelText(/^Numer zamówienia/), "45767");
    await user.type(screen.getByLabelText("Stawka kosztowa"), "120");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );

    // Pierwszy atomowy request nie utworzył rekordu, więc retry ponawia POST.
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(2),
    );
    expect(dlPortalApi.updateOrder).not.toHaveBeenCalled();
  });

  it("dialog otwarty po edycji inline dopisuje do tego samego szkicu", async () => {
    // Odświeżenie listy jest asynchroniczne, więc zaraz po pierwszym zapisie
    // `activeOrder` wciąż jest `null`. Pamięć `draftOrderId` musi obowiązywać
    // także ścieżkę dialogową — inaczej powstaje drugi szkic tego samego
    // zamówienia.
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      await screen.findByRole("button", { name: /Edytuj: Numer zamówienia/i }),
    );
    await user.type(screen.getByLabelText("Numer zamówienia"), "45767");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );

    await user.click(
      screen.getByRole("button", { name: "Uzupełnij zamówienie" }),
    );
    // Numer jest wymagany przez `canSubmit`, a dialog otwiera się pusty.
    await user.type(await screen.findByLabelText(/^Numer zamówienia/), "45767");
    await user.type(screen.getByLabelText("Stawka przychodowa"), "180");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(dlPortalApi.updateOrder).toHaveBeenCalledWith(
        7,
        4242,
        expect.objectContaining({ rate_client: 180 }),
      ),
    );
    expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1);
  });

  it("stawka kosztowa zapisuje się przez świeżo utworzone zamówienie", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      await screen.findByRole("button", { name: /Edytuj: Stawka kosztowa/i }),
    );
    await user.type(screen.getByLabelText("Stawka kosztowa"), "120");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );
    const [, form] = vi.mocked(dlPortalApi.createOrderExtension).mock.calls[0];
    expect((form as FormData).get("rate_candidate")).toBe("120");
    expect(dlPortalApi.updateOrder).not.toHaveBeenCalled();
  });
});


describe("ContractorOrderPanel — promocja draftu z dialogu", () => {
  it("zapis istniejącego zamówienia NIE wysyła statusu", async () => {
    // Sprzężenie łatwe do zerwania: `_auto_activate_unless_status_explicit`
    // po stronie serwera USTĘPUJE jawnemu `status` w ciele PATCH-a (bo
    // `PATCH {"status":"draft"}` → `DELETE` to udokumentowana droga kasowania
    // zamówienia). Gdyby ten formularz kiedykolwiek zaczął dosyłać status,
    // promocja draft → aktywne umarłaby po cichu: pola byłyby uzupełnione,
    // a wiersz zostałby w „Draft".
    const draftOnly = {
      ...structuredClone(CONTRACTOR),
      contract_id: 808,
      candidate_name: "Do Uzupelnienia",
      orders: [
        makeOrder({
          id: 55,
          title: "D-9",
          status: "draft",
          start_date: localISO(-2),
          end_date: localISO(100),
          rate_client: null,
        }),
      ],
    };
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [draftOnly],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);

    const user = userEvent.setup();
    renderPanel();

    await user.click(
      await screen.findByRole("button", { name: "Uzupełnij zamówienie" }),
    );
    await user.type(screen.getByLabelText("Stawka przychodowa"), "180");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(dlPortalApi.updateOrder).toHaveBeenCalledTimes(1),
    );
    const [, , payload] = vi.mocked(dlPortalApi.updateOrder).mock.calls[0];
    expect(payload).not.toHaveProperty("status");
    expect(payload).toMatchObject({ rate_client: 180 });
  });
});

describe("ContractorOrderPanel — e-Zdrowie bez zamówienia", () => {
  // `POST /orders` wymaga umowy wykonawczej dla Centrum e-Zdrowia, a select
  // renderował się wyłącznie przy `activeOrder`. U TEGO klienta ścieżka
  // „kontraktor bez zamówienia" kończyła się więc 422 i objaw „nie da się nic
  // wpisać" przeżywał poprawkę — a pola, z którego można by umowę podać,
  // karta w tym stanie w ogóle nie renderowała.
  const NO_ORDERS = {
    ...structuredClone(CONTRACTOR),
    contract_id: 815,
    candidate_name: "Ezdrowie Bezzamowien",
    rate_candidate: null,
    latest_order_rate_client: null,
    orders: [],
  };

  const STRUCTURE = {
    framework_contracts: [
      {
        id: 2,
        name: "CeZ/145/2025 – cz. II",
        project_part: "cz2",
        status: "active",
        executive_contracts: [
          {
            id: 10,
            number: "CeZ/145/2025/UW-1",
            status: "active",
            framework_contract_id: 2,
            project_part: "cz2",
            notes: null,
            consultants_count: 0,
            created_at: null,
          },
        ],
      },
      {
        id: 4,
        name: "CeZ/147/2025 – cz. IV",
        project_part: "cz4",
        status: "active",
        executive_contracts: [],
      },
    ],
  };

  beforeEach(() => {
    executiveContractMocks.structure.mockReset();
    executiveContractMocks.structure.mockResolvedValue(STRUCTURE);
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [NO_ORDERS],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
  });

  it("select umowy wykonawczej renderuje się MIMO braku zamówienia, pogrupowany po częściach", async () => {
    renderPanel(EZDROWIE_CLIENT_ID);
    const select = await screen.findByLabelText("Umowa wykonawcza");
    // Opcje dojeżdżają po odpowiedzi struktury.
    await waitFor(() =>
      expect(select.querySelectorAll("optgroup")).toHaveLength(1),
    );
    expect(select.querySelector("optgroup")?.label).toBe("Cz. II — CeZ/145/2025");
    // Część bez aktywnej umowy nie ma grupy — nie da się do niej przypisać.
    expect(screen.queryByText("Cz. IV — CeZ/147/2025")).not.toBeInTheDocument();
    // Selektu części umowy już nie ma — część jest wartością pochodną.
    expect(screen.queryByLabelText("Część umowy")).not.toBeInTheDocument();
  });

  it("wybór umowy wykonawczej zakłada szkic zamówienia i przesyła executive_contract_id", async () => {
    const user = userEvent.setup();
    renderPanel(EZDROWIE_CLIENT_ID);

    const select = await screen.findByLabelText("Umowa wykonawcza");
    await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2));
    await user.selectOptions(select, "10");

    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );
    const [, form] = vi.mocked(dlPortalApi.createOrderExtension).mock.calls[0];
    expect((form as FormData).get("executive_contract_id")).toBe("10");
    expect((form as FormData).get("project_part")).toBeNull();
    expect((form as FormData).get("order_status")).toBe("draft");
  });

  it("zapis innego pola bez umowy wykonawczej odmawia PO POLSKU i nie woła API", async () => {
    // Bez tej gałęzi użytkownik dostawał surowe „Request failed with status
    // code 422" — komunikat, z którego nie da się wywnioskować, czego brakuje.
    const user = userEvent.setup();
    renderPanel(EZDROWIE_CLIENT_ID);

    await user.click(
      await screen.findByRole("button", { name: /Edytuj: Numer zamówienia/i }),
    );
    await user.type(screen.getByLabelText("Numer zamówienia"), "45767");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(
      await screen.findByText(/wybierz umowę wykonawczą/i),
    ).toBeInTheDocument();
    expect(dlPortalApi.createOrderExtension).not.toHaveBeenCalled();
  });

  it("drugi zapis PRZED odświeżeniem trafia w ten sam szkic, nie tworzy kolejnego", async () => {
    // `onChange()` odświeża listę asynchronicznie, więc w okienku między
    // utworzeniem szkicu a nadejściem danych `activeOrder` jest jeszcze null.
    // Bez zapamiętanego id kolejny zapis zakładałby DRUGI szkic tego samego
    // zamówienia — a wybór umowy wykonawczej stawia obowiązkowy krok dokładnie
    // przed innymi edycjami, czyli robi z tego zwykłą kolejność klikania.
    const user = userEvent.setup();
    renderPanel(EZDROWIE_CLIENT_ID);

    const select = await screen.findByLabelText("Umowa wykonawcza");
    await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2));
    await user.selectOptions(select, "10");
    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );

    await user.click(
      screen.getByRole("button", { name: /Edytuj: Numer zamówienia/i }),
    );
    await user.type(screen.getByLabelText("Numer zamówienia"), "45767");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(dlPortalApi.updateOrder).toHaveBeenCalledWith(
        EZDROWIE_CLIENT_ID,
        4242,
        { title: "45767" },
      ),
    );
    expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1);
  });

  it("bez żadnej aktywnej umowy wykonawczej select odsyła do sekcji Struktura umów", async () => {
    executiveContractMocks.structure.mockResolvedValue({
      framework_contracts: [
        { ...STRUCTURE.framework_contracts[0], executive_contracts: [] },
      ],
    });
    renderPanel(EZDROWIE_CLIENT_ID);
    expect(
      await screen.findByText(
        "Dodaj umowę wykonawczą w sekcji Struktura umów na profilu klienta.",
      ),
    ).toBeInTheDocument();
  });

  it("u klienta spoza e-Zdrowia umowa wykonawcza się NIE pojawia", async () => {
    // Bramka jest po `client_id`, nie po nazwie — a backend odrzuca umowę
    // wykonawczą przysłaną przez kogokolwiek innego.
    renderPanel(7);
    expect(await screen.findByText(/Ezdrowie Bezzamowien/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Umowa wykonawcza")).not.toBeInTheDocument();
    expect(executiveContractMocks.structure).not.toHaveBeenCalled();
  });
});

// ── Przycisk „Zakończ" ───────────────────────────────────────────────────────

// ── Zamówienie kończące się jutro (zgłoszenie 29.09.2026) ────────────────────

describe("ContractorOrderPanel — komunikat o zamówieniu kończącym się w najbliższych dniach", () => {
  const NUMBER = "K/2026/197070/ŁO/477/26APP";

  /** Kontraktor z zamówieniami i polami, które serwer liczy w odpowiedzi listy. */
  function mockContractor(
    orders: ClientOrderRead[],
    server: {
      ending_without_successor_order_id?: number | null;
      ending_without_successor_days?: number | null;
    } = {},
  ) {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          {
            ...structuredClone(CONTRACTOR),
            contract_id: 479,
            candidate_name: "Mariusz Matyszczuk",
            contract_status: "active",
            days_to_latest_end: 1,
            orders,
            ...server,
          },
        ],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
  }

  const period = { start_date: localISO(-90), end_date: localISO(1) };

  it("zamówienie trwające i kończące się jutro mówi „kończy się za 1 dzień” — bez numeru i bez słowa „przyszłe”", async () => {
    // Kontrakt #479: stary `completed` z importu Excela stoi w kolekcji PRZED
    // aktywnym wierszem tego samego okresu. Serwer wskazuje aktywny (#464).
    mockContractor(
      [
        makeOrder({ id: 15, title: NUMBER, status: "completed", ...period }),
        makeOrder({ id: 464, title: NUMBER, status: "active", ...period }),
      ],
      { ending_without_successor_order_id: 464, ending_without_successor_days: 1 },
    );
    renderPanel();

    const badge = await screen.findByTestId("order-ending-badge");
    expect(badge).toHaveTextContent(/^kończy się za 1 dzień$/);
    expect(badge.textContent).not.toMatch(/przyszłe|K\/2026/);
    // Aktywne zamówienie obsługuje kontraktora — żadnego „Brak aktywnego”.
    expect(screen.queryByTestId("no-active-order-note")).toBeNull();
    expect(screen.getByText("Brak przyszłych zamówień.")).toBeInTheDocument();
    // Zamknięty duplikat idzie do historii, nie do górnego slotu.
    expect(screen.getByText(/Historia zamówień \(1\)/)).toBeInTheDocument();
  });

  it("„Zakończ zamówienie” działa na AKTYWNYM wierszu, nie na zamkniętym duplikacie", async () => {
    vi.mocked(dlPortalApi.closeOrder).mockResolvedValue({ data: { id: 464 } } as never);
    mockContractor(
      [
        makeOrder({ id: 15, title: NUMBER, status: "completed", ...period }),
        makeOrder({ id: 464, title: NUMBER, status: "active", ...period }),
      ],
      { ending_without_successor_order_id: 464, ending_without_successor_days: 1 },
    );
    renderPanel();
    await screen.findByTestId("order-ending-badge");

    fireEvent.click(screen.getByRole("button", { name: /^Zakończ zamówienie$/ }));
    const dateInput = await screen.findByLabelText(/Data zakończenia zamówienia/);
    fireEvent.change(dateInput, { target: { value: localISO(1) } });
    fireEvent.click(
      screen.getAllByRole("button", { name: /^Zakończ zamówienie$/ }).at(-1)!,
    );

    await waitFor(() =>
      expect(dlPortalApi.closeOrder).toHaveBeenCalledWith(
        7,
        464,
        expect.objectContaining({ closure_date: localISO(1) }),
      ),
    );
  });

  it("jedno aktywne zamówienie kończące się jutro: ten sam komunikat i przycisk „Zakończ zamówienie”", async () => {
    // Wzorzec z kafelków, które działały (Żółtaniecki #478, Augustyniak #619).
    mockContractor(
      [makeOrder({ id: 585, title: "K/2026/194208/JP/828/26ERSTE8", ...period })],
      { ending_without_successor_order_id: 585, ending_without_successor_days: 1 },
    );
    renderPanel();

    expect(await screen.findByTestId("order-ending-badge")).toHaveTextContent(
      /^kończy się za 1 dzień$/,
    );
    expect(screen.queryByTestId("no-active-order-note")).toBeNull();
    expect(
      screen.getByRole("button", { name: /^Zakończ zamówienie$/ }),
    ).toBeInTheDocument();
  });

  it("kończące się dziś zamówienie też jest aktywne i mówi „dziś”", async () => {
    mockContractor(
      [
        makeOrder({
          id: 586,
          title: "TODAY-1",
          start_date: localISO(-30),
          end_date: localISO(0),
        }),
      ],
      { ending_without_successor_order_id: 586, ending_without_successor_days: 0 },
    );
    renderPanel();

    expect(await screen.findByTestId("order-ending-badge")).toHaveTextContent(
      /^kończy się dziś$/,
    );
    expect(screen.queryByTestId("no-active-order-note")).toBeNull();
    expect(
      screen.getByRole("button", { name: /^Zakończ zamówienie$/ }),
    ).toBeInTheDocument();
  });

  it("jedyne zamówienie, które jeszcze się nie zaczęło, stoi w górnym slocie i mówi „kończy się za N dni”", async () => {
    // Nic nie trwa, więc najbliższe przyszłe zamówienie jest „bieżącą pozycją"
    // karty (`splitOrders`) — plakietka nie może twierdzić „przyszłe zamówienie",
    // skoro karta nie ma sekcji przyszłych zamówień.
    mockContractor(
      [
        makeOrder({
          id: 700,
          title: "SOLO-FUTURE",
          start_date: localISO(3),
          end_date: localISO(20),
        }),
      ],
      { ending_without_successor_order_id: 700, ending_without_successor_days: 20 },
    );
    renderPanel();

    expect(await screen.findByTestId("order-ending-badge")).toHaveTextContent(
      /^kończy się za 20 dni$/,
    );
    expect(screen.queryByTestId("no-active-order-note")).toBeNull();
  });

  it("przyszłe zamówienie obok zamkniętego historycznego stoi na liście przyszłych i tak jest nazwane", async () => {
    mockContractor(
      [
        makeOrder({
          id: 701,
          title: "NEXT-3",
          start_date: localISO(3),
          end_date: localISO(20),
        }),
        makeOrder({
          id: 699,
          title: "OLD-DONE",
          status: "completed",
          start_date: localISO(-100),
          end_date: localISO(-10),
        }),
      ],
      { ending_without_successor_order_id: 701, ending_without_successor_days: 20 },
    );
    renderPanel();

    expect(await screen.findByTestId("order-ending-badge")).toHaveTextContent(
      "przyszłe zamówienie NEXT-3 kończy się za 20 dni",
    );
  });

  it("„przyszłe zamówienie …” tylko dla zamówienia, którego okres jeszcze się nie zaczął", async () => {
    // Kontrakt #145: bieżące zamówienie ma kontynuację, a to PRZYSZŁE samo
    // kończy się za 20 dni i nic po nim nie ma — ono ostrzega.
    mockContractor(
      [
        makeOrder({
          id: 656,
          title: "NEXT-2",
          start_date: localISO(5),
          end_date: localISO(20),
        }),
        makeOrder({
          id: 655,
          title: "CUR-2",
          start_date: localISO(-100),
          end_date: localISO(4),
        }),
      ],
      { ending_without_successor_order_id: 656, ending_without_successor_days: 20 },
    );
    renderPanel();

    expect(await screen.findByTestId("order-ending-badge")).toHaveTextContent(
      "przyszłe zamówienie NEXT-2 kończy się za 20 dni",
    );
    expect(screen.queryByTestId("no-active-order-note")).toBeNull();
  });
});

describe("ContractorOrderPanel — przyciski „Zakończ zamówienie” i „Zakończ współpracę”", () => {
  /** Kontraktor o zadanym statusie kontraktu, z jednym aktywnym zamówieniem. */
  function withContractStatus(contract_status: string) {
    return {
      ...structuredClone(CONTRACTOR),
      contract_id: 600,
      candidate_name: "Wojciech Sokolnicki",
      contract_status,
      orders: [
        makeOrder({
          id: 61,
          title: "Z-600",
          contract_id: 600,
          contract_status,
          status: "active",
          start_date: localISO(-60),
          end_date: null,
        }),
      ],
    };
  }

  function mockContractor(contract_status: string) {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [withContractStatus(contract_status)],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
  }

  it("kontrakt SZKICOWY z aktywnym zamówieniem MA „Zakończ współpracę”", async () => {
    // Realny przypadek Banku Pocztowego: kontraktor pracuje, a kontrakt jest
    // szkicem, bo dialog „Nowy kontraktor" nie zbiera typu umowy ani trybu
    // pracy. Bramka na `active` chowała jedyną drogę rozstania z pracującym
    // konsultantem. Backendowy `terminate` bramki statusu nie ma.
    //
    // (Pierwotną przyczyną tego szkicu było wymaganie `end_date` w bramce
    // aktywacji — zdjęte w sierpniu 2026; scenariusz zostaje realny bez niego.)
    mockContractor("draft");
    renderPanel();
    await screen.findByRole("heading", { name: /Wojciech Sokolnicki/ });
    expect(
      screen.getByRole("button", { name: /^Zakończ współpracę…$/ }),
    ).toBeInTheDocument();
  });

  it.each(["active", "ending", "ready_for_signature"])(
    "kontrakt w stanie %s MA „Zakończ współpracę”",
    async (status) => {
      mockContractor(status);
      renderPanel();
      await screen.findByRole("heading", { name: /Wojciech Sokolnicki/ });
      expect(
        screen.getByRole("button", { name: /^Zakończ współpracę…$/ }),
      ).toBeInTheDocument();
    },
  );

  it.each(["ended", "void"])(
    "kontrakt w stanie terminalnym %s NIE MA „Zakończ współpracę”",
    async (status) => {
      mockContractor(status);
      renderPanel();
      await screen.findByRole("heading", { name: /Wojciech Sokolnicki/ });
      expect(
        screen.queryByRole("button", { name: /^Zakończ współpracę…$/ }),
      ).not.toBeInTheDocument();
    },
  );

  it("„Zakończ zamówienie” woła wąski endpoint zamówienia, nie terminację umowy", async () => {
    // Sedno ticketu: wypowiedzenie umowy domyka WSZYSTKIE zamówienia
    // kontraktu, w tym linię rozliczaną w MD. Zakończenie zamówienia
    // okresowego musi trafiać w jeden wiersz.
    vi.mocked(dlPortalApi.closeOrder).mockResolvedValue({
      data: { id: 61 },
    } as never);
    mockContractor("active");
    renderPanel();
    await screen.findByRole("heading", { name: /Wojciech Sokolnicki/ });

    fireEvent.click(screen.getByRole("button", { name: /^Zakończ zamówienie$/ }));
    const dateInput = await screen.findByLabelText(
      /Data zakończenia zamówienia/,
    );
    fireEvent.change(dateInput, { target: { value: "2026-09-30" } });
    fireEvent.click(
      screen.getAllByRole("button", { name: /^Zakończ zamówienie$/ }).at(-1)!,
    );

    await waitFor(() =>
      expect(dlPortalApi.closeOrder).toHaveBeenCalledWith(
        7,
        61,
        expect.objectContaining({ closure_date: "2026-09-30" }),
      ),
    );
    expect(contractsApi.update).not.toHaveBeenCalled();
  });

  it("„Usuń zamówienie” przy bieżącym zamówieniu kasuje tylko ten wiersz", async () => {
    // Ticket 09.2026: bieżące zamówienie nie miało kosza, a jedynym czerwonym
    // przyciskiem z ikoną kosza było „Zakończ współpracę”, które wypowiada
    // umowę i domyka wszystkie zamówienia osoby.
    //
    // Audyt 18.09.2026: potwierdzenie przestało być natywnym `confirm`
    // z obietnicą „umowa tej osoby nie zmieni się” — nieprawdziwą, bo
    // kasowanie zabiera przez CASCADE krok stawki klienta. Dialog pyta serwer,
    // CO się przeceni, i dopiero wtedy odsłania przycisk.
    mockContractor("active");
    renderPanel();
    await screen.findByRole("heading", { name: /Wojciech Sokolnicki/ });

    await openDeleteFromMenu();

    // Otwiera się dialog, nie mutacja: samo kliknięcie kosza NIE kasuje.
    await screen.findByRole("heading", { name: /Usunąć zamówienie/ });
    expect(dlPortalApi.deleteOrder).not.toHaveBeenCalled();

    const confirmButton = await screen.findByRole("button", {
      name: /^Usuń zamówienie$/,
      // Przycisk w stopce dialogu jest aktywny dopiero po odpowiedzi serwera.
    });
    await waitFor(() => expect(confirmButton).not.toBeDisabled());
    fireEvent.click(confirmButton);

    await waitFor(() =>
      expect(dlPortalApi.deleteOrder).toHaveBeenCalledWith(7, 61),
    );
    expect(contractsApi.update).not.toHaveBeenCalled();
    expect(dlPortalApi.closeOrder).not.toHaveBeenCalled();
  });

  it("dialog usuwania wymienia przeceniony okres zamiast obiecywać, że nic się nie zmieni", async () => {
    // Kontrakt 167 z produkcji: usunięcie zamówienia 351 przecenia
    // marzec–sierpień z 185,00 na 178,00 zł/h. Stary `confirm` twierdził,
    // że umowa tej osoby się nie zmieni.
    vi.mocked(dlPortalApi.previewOrderDeletion).mockResolvedValueOnce({
      data: {
        order_id: 61,
        order_number: "61",
        status: "active",
        is_group_line: false,
        deletes_row: true,
        blocked_by: [],
        has_file: false,
        rate_changes: [
          {
            effective_from: "2026-03-01",
            effective_until: "2026-09-01",
            rate: 185,
            replacement_rate: 178,
            changes_amount: true,
          },
        ],
        currency: "PLN",
        rate_unit: "hourly",
        amounts_redacted: false,
      },
    } as never);
    mockContractor("active");
    renderPanel();
    await screen.findByRole("heading", { name: /Wojciech Sokolnicki/ });

    await openDeleteFromMenu();

    expect(await screen.findByText(/przeceniony z 185,00 PLN\/h/)).toBeInTheDocument();
    expect(screen.getByText(/01\.03\.2026/)).toBeInTheDocument();
  });

  it("„Zakończ współpracę” nie wygląda jak usuwanie (bez ikony kosza)", async () => {
    mockContractor("active");
    renderPanel();
    await screen.findByRole("heading", { name: /Wojciech Sokolnicki/ });
    const terminate = screen.getByRole("button", { name: /^Zakończ współpracę…$/ });
    expect(terminate.querySelector("svg[class*='trash']")).toBeNull();
  });
});

describe("reactivation after completing an order", () => {
  it.each(["success", "save_failure", "upload_failure"])(
    "keeps the existing card synchronized: %s",
    async (outcome) => {
      const user = userEvent.setup();
      let saved = false;
      const updated = { ...HISTORY, status: "active", start_date: localISO(-6), end_date: localISO(100) };
      vi.mocked(dlPortalApi.listContractorsWithOrders).mockImplementation(async () => ({
        data: {
          contractors: [{ ...structuredClone(CONTRACTOR), orders: [saved ? updated : HISTORY] }],
          total_contractors: 1,
          can_manage_finance: true,
        },
      }) as never);
      vi.mocked(dlPortalApi.updateOrder).mockImplementation(async () => {
        if (outcome === "save_failure") throw new Error("Zapis odrzucony");
        saved = true;
        return { data: updated } as never;
      });
      vi.mocked(dlPortalApi.replaceOrderPo).mockRejectedValue(new Error("Upload odrzucony"));
      renderPanel();
      expect(await screen.findByTestId("no-active-order-note")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Uzupełnij zamówienie" }));
      fireEvent.change(screen.getByLabelText("Data od"), { target: { value: updated.start_date } });
      fireEvent.change(screen.getByLabelText("Data do"), { target: { value: updated.end_date } });
      if (outcome === "upload_failure") {
        fireEvent.change(screen.getByLabelText(/Zamień plik PDF/i), {
          target: { files: [new File(["pdf"], "order.pdf", { type: "application/pdf" })] },
        });
      }
      await user.click(screen.getByRole("button", { name: "Zapisz" }));
      await waitFor(() => expect(dlPortalApi.updateOrder).toHaveBeenCalledTimes(1));
      if (outcome === "save_failure") {
        expect(await screen.findByText("Zapis odrzucony")).toBeInTheDocument();
        expect(screen.getByTestId("no-active-order-note")).toBeInTheDocument();
        expect(dlPortalApi.listContractorsWithOrders).toHaveBeenCalledTimes(1);
      } else {
        await waitFor(() => expect(screen.queryByTestId("no-active-order-note")).toBeNull());
        expect(dlPortalApi.listContractorsWithOrders).toHaveBeenCalledTimes(2);
        if (outcome === "upload_failure") {
          expect(await screen.findByText("Upload odrzucony")).toBeInTheDocument();
          expect(screen.getByRole("dialog", { name: "Uzupełnij zamówienie" })).toBeInTheDocument();
        } else {
          await waitFor(() => expect(screen.queryByRole("dialog", { name: "Uzupełnij zamówienie" })).toBeNull());
          expect(screen.getByText("Zamówienie zaktualizowane")).toBeInTheDocument();
        }
      }
    },
  );
});


// ── Panel: nowe zachowania (wersja B, 29.09.2026) ────────────────────────────

describe("ContractorOrderPanel — bramka roli „Zakończ współpracę”", () => {
  it("rekruter (bez zarządzania statusem kontraktu) nie widzi „Zakończ współpracę”", async () => {
    authState.role = "recruiter";
    authState.capabilities = [];
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(
      screen.queryByRole("button", { name: /^Zakończ współpracę/ }),
    ).not.toBeInTheDocument();
  });

  it("admin w trybie „podgląd jako” nie widzi „Zakończ współpracę”", async () => {
    impersonation.realUser = { role: "admin" };
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(
      screen.queryByRole("button", { name: /^Zakończ współpracę/ }),
    ).not.toBeInTheDocument();
  });

  it("Delivery Lead widzi „Zakończ współpracę” i otwiera okno zakończenia", async () => {
    authState.role = "delivery_lead";
    authState.capabilities = [];
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(
      screen.getByRole("button", { name: /^Zakończ współpracę…$/ }),
    ).toBeInTheDocument();
  });
});

describe("ContractorOrderPanel — PDF bieżącego zamówienia", () => {
  function mockActive(hasFile: boolean) {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          {
            ...structuredClone(CONTRACTOR),
            orders: [
              {
                ...structuredClone(ACTIVE),
                has_file: hasFile,
                filename: hasFile ? "zamowienie_45767.pdf" : null,
                content_type: hasFile ? "application/pdf" : null,
              },
            ],
          },
        ],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
  }

  it("bez pliku nie ma przycisków „Otwórz” i „Pobierz”", async () => {
    mockActive(false);
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.queryByRole("button", { name: /Otwórz/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pobierz/ })).not.toBeInTheDocument();
  });

  it("z plikiem pokazuje nazwę, „Otwórz” i „Pobierz” — oba przez endpoint z tokenem", async () => {
    mockActive(true);
    fileMocks.download.mockResolvedValue(undefined);
    fileMocks.open.mockResolvedValue(undefined);
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getByText("zamowienie_45767.pdf")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Pobierz/ }));
    await waitFor(() =>
      expect(fileMocks.download).toHaveBeenCalledWith(
        "/api/clients/7/orders/1/file",
        "zamowienie_45767.pdf",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: /Otwórz/ }));
    await waitFor(() =>
      expect(fileMocks.open).toHaveBeenCalledWith(
        "/api/clients/7/orders/1/file",
        "application/pdf",
        "zamowienie_45767.pdf",
      ),
    );
  });

  it("nieudane pobranie mówi o tym po polsku", async () => {
    mockActive(true);
    fileMocks.download.mockRejectedValue(new Error("boom"));
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    fireEvent.click(screen.getByRole("button", { name: /Pobierz/ }));
    expect(
      await screen.findByText("Nie udało się pobrać pliku zamówienia."),
    ).toBeInTheDocument();
  });
});

describe("ContractorOrderPanel — karta szkicu", () => {
  const DRAFT_CARD = {
    ...structuredClone(CONTRACTOR),
    contract_id: 690,
    candidate_name: "Jan Maj",
    draft_card: true,
    orders: [],
  };

  function renderDraft(onAssignToOrder = vi.fn()) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <ContractorOrderPanel
            contractor={DRAFT_CARD as never}
            clientId={7}
            canManageOrders
            canManageFinance
            canViewFinance
            suggestedOrderType="periodic"
            legacyNullOrderType="periodic"
            onAssignToOrder={onAssignToOrder}
            onClose={() => undefined}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );
    return onAssignToOrder;
  }

  it("ma „Przypisz do zamówienia”, „Uzupełnij zamówienie” i „Usuń szkic”, bez menu usuwania zamówienia", async () => {
    const onAssign = renderDraft();
    expect(screen.getByTestId("no-active-order-note")).toHaveTextContent("Brak zamówienia");
    expect(screen.getByRole("button", { name: "Uzupełnij zamówienie" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Usuń szkic" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Więcej akcji zamówienia" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Przypisz do zamówienia" }));
    expect(onAssign).toHaveBeenCalledWith(
      expect.objectContaining({ contract_id: 690 }),
      expect.any(Function),
    );
  });

  it("„Usuń szkic” pyta w oknie i dopiero potwierdzenie woła serwer", async () => {
    vi.mocked(dlPortalApi.dismissDraftCard).mockResolvedValue({ data: {} } as never);
    renderDraft();
    fireEvent.click(screen.getByRole("button", { name: "Usuń szkic" }));
    const dialog = await screen.findByRole("dialog", { name: "Usunąć szkic?" });
    expect(dlPortalApi.dismissDraftCard).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Usuń szkic" }));
    await waitFor(() =>
      expect(dlPortalApi.dismissDraftCard).toHaveBeenCalledWith(7, 690),
    );
  });

  it("bez `onAssignToOrder` (klient spoza CeZ) nie ma „Przypisz do zamówienia”", async () => {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <ContractorOrderPanel
            contractor={DRAFT_CARD as never}
            clientId={7}
            canManageOrders
            canManageFinance
            canViewFinance
            suggestedOrderType="periodic"
            legacyNullOrderType="periodic"
            onClose={() => undefined}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(
      screen.queryByRole("button", { name: "Przypisz do zamówienia" }),
    ).not.toBeInTheDocument();
  });
});

describe("ContractorOrderPanel — redakcja kwot i zamykanie", () => {
  it("rola bez kwot widzi „—” w wierszach Koszt i Przychód", async () => {
    authState.role = "tac";
    authState.capabilities = [];
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [structuredClone(CONTRACTOR)],
        total_contractors: 1,
        can_manage_finance: false,
      },
    } as never);
    renderPanel();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    const cost = screen.getByText("Koszt").nextElementSibling;
    const revenue = screen.getByText("Przychód").nextElementSibling;
    expect(cost).toHaveTextContent(/^—$/);
    expect(revenue).toHaveTextContent(/^—$/);
    expect(screen.queryByText(/180/)).not.toBeInTheDocument();
  });

  it("przycisk zamykania woła `onClose`", async () => {
    const onClose = vi.fn();
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <ContractorOrderPanel
            contractor={structuredClone(CONTRACTOR) as never}
            clientId={7}
            canManageOrders
            canManageFinance
            canViewFinance
            suggestedOrderType="periodic"
            legacyNullOrderType="periodic"
            onClose={onClose}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Zamknij panel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("kończące się zamówienie stawia „Dodaj przedłużenie” jako główną akcję", async () => {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          {
            ...structuredClone(CONTRACTOR),
            ending_without_successor_order_id: 90,
            ending_without_successor_days: 1,
            orders: [
              makeOrder({
                id: 90,
                title: "END-1",
                start_date: localISO(-30),
                end_date: localISO(1),
              }),
            ],
          },
        ],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    renderPanel();
    await screen.findByTestId("order-ending-badge");
    const footerButtons = screen
      .getAllByRole("button")
      .filter((b) => /Dodaj przedłużenie|Uzupełnij zamówienie/.test(b.textContent ?? ""));
    expect(footerButtons[0]).toHaveTextContent("Dodaj przedłużenie");
  });
});

// Przeniesione z testu dawnych kafelków (`ContractorOrderCards`, do 29.09.2026):
// link z panelu „Moi klienci" (`?order=`) trafia do panelu kontraktora.
describe("ContractorOrderPanel — deep link z panelu „Moi klienci”", () => {
  function renderWithFocus(focusOrder: ContractorOrderFocus | null) {
    const onFocusOrderServed = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const draft = makeOrder({ id: 77, title: "Tomasz Sadowski — DevOps", status: "draft" });
    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <ContractorOrderPanel
            clientId={7}
            contractor={{ ...structuredClone(CONTRACTOR), orders: [draft] } as never}
            canViewFinance
            canManageFinance
            canManageOrders
            suggestedOrderType="periodic"
            legacyNullOrderType="periodic"
            focusOrder={focusOrder}
            onFocusOrderServed={onFocusOrderServed}
            onClose={() => undefined}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );
    return { onFocusOrderServed };
  }

  it("szkic z linku otwiera się od razu w oknie „Uzupełnij zamówienie” i zgłasza obsłużenie", async () => {
    const { onFocusOrderServed } = renderWithFocus({
      contractId: 529,
      orderId: 77,
      openEditor: true,
      nonce: 1,
    });
    expect(
      await screen.findByRole("dialog", { name: "Uzupełnij zamówienie" }),
    ).toBeInTheDocument();
    expect(onFocusOrderServed).toHaveBeenCalledTimes(1);
  });

  it("cel innego kontraktora nic nie otwiera", async () => {
    const { onFocusOrderServed } = renderWithFocus({
      contractId: 999,
      orderId: 77,
      openEditor: true,
      nonce: 1,
    });
    await screen.findByTestId("contractor-order-panel");
    expect(screen.queryByRole("dialog", { name: "Uzupełnij zamówienie" })).toBeNull();
    expect(onFocusOrderServed).not.toHaveBeenCalled();
  });

  it("bez celu nic się nie otwiera", async () => {
    renderWithFocus(null);
    await screen.findByTestId("contractor-order-panel");
    expect(screen.queryByRole("dialog", { name: "Uzupełnij zamówienie" })).toBeNull();
  });
});
