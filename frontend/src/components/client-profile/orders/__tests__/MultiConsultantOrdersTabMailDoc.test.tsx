/**
 * „Rozstrzygnij w oknie zamówienia" z kolejki zamówień z maila (ticket 09.2026).
 *
 * Mail z osobą nieaktywną/nieznalezioną na zamówieniu MD/kosztowym nie jest
 * zapisywany automatem. Kolejka prowadzi do zakładki zamówień klienta, która
 * pobiera PDF dokumentu i otwiera TO SAMO okno co przy ręcznym wgraniu pliku:
 * „Uzupełnij zamówienie", gdy zamówienie o tym numerze już jest, inaczej „Nowe
 * zamówienie". Po zapisie dokument schodzi z kolejki.
 *
 * Nazwiska i kwoty zmyślone (repo publiczne).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { MultiConsultantOrdersTab } from "@/components/client-profile/orders/MultiConsultantOrdersTab";
import type { OrderGroupExtraction, OrderGroupRead } from "@/lib/api/orderGroups";

vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (s: { user: { role: string; capabilities: string[] } }) => unknown,
  ) => selector({ user: { role: "admin", capabilities: ["manage_finance"] } }),
  hasRole: (user: { role?: string } | null, ...roles: string[]) =>
    roles.includes(user?.role ?? ""),
  canManageMultiConsultantOrders: () => true,
  canEditOrderLineAmounts: () => true,
  canManageOrderLifecycle: () => true,
  canManageCandidateFinance: () => true,
  canViewClientFinance: () => true,
}));

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    addLines: vi.fn(),
    extractPlan: vi.fn(),
    consultantOptions: vi.fn(),
    events: vi.fn(),
    replaceFile: vi.fn(),
  },
  mdConsumptionApi: {},
}));

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    listActiveContractsForExtension: vi.fn(),
    listContractorsWithOrders: vi.fn().mockResolvedValue({
      data: { contractors: [], total_contractors: 0, can_manage_finance: true },
    }),
    extractOrderPdf: vi.fn(),
  },
}));

vi.mock("@/lib/api/orderMail", () => ({
  orderMailApi: {
    orderTarget: vi.fn(),
    resolvedInOrder: vi.fn(),
    fileUrl: (id: number) => `/api/order-mail/queue/${id}/file`,
  },
}));

vi.mock("@/lib/authenticated-files", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/authenticated-files")>()),
  fetchAuthenticatedBlob: vi.fn(),
}));

import { fetchAuthenticatedBlob } from "@/lib/authenticated-files";
import { orderGroupsApi } from "@/lib/api/orderGroups";
import { orderMailApi } from "@/lib/api/orderMail";

const GROUP = {
  id: 77,
  client_id: 7,
  order_number: "SAP 4500000777",
  start_date: "2031-01-01",
  end_date: null,
  notes: null,
  created_at: "2031-01-01T10:00:00Z",
  status: "active",
  status_label: "Aktywne",
  closure_date: null,
  closure_reason: null,
  order_type: "cost",
  is_cost_based: true,
  is_md_budget_based: false,
  budget_amount: 40000,
  budget_used: 0,
  budget_remaining: 40000,
  budget_manual_adjustment: null,
  md_budget_total: null,
  md_budget_used: null,
  md_budget_remaining: null,
  md_budget_manual_adjustment: null,
  predecessor_group_id: null,
  filename: null,
  has_file: false,
  content_type: null,
  size_bytes: null,
  file_uploaded_at: null,
  can_add_consultant: true,
  executive_contract: null,
  md_positions_total: null,
  md_used_total: null,
  contract_value_pln: null,
  used_value_pln: null,
  lines: [],
  active_consultants: 0,
  event_count: 0,
  future_orders: [],
} as unknown as OrderGroupRead;

const PLAN: OrderGroupExtraction = {
  order_number: "SAP 4500000777",
  start_date: "2031-01-01",
  end_date: null,
  open_ended: true,
  total_value: 40000,
  currency: "PLN",
  md_total: null,
  suggested_order_type: "cost",
  client_policy: "Polkomtel",
  consultant_ref: null,
  title_needs_review: false,
  document_incomplete: false,
  uncertain: false,
  uncertain_reasons: [],
  md_scope: null,
  lines: [
    {
      ordinal: 1,
      document_name: "Marian Odchodzący",
      position_label: null,
      rate_revenue: 1280,
      rate_revenue_unit: "day",
      rate_revenue_gross: null,
      md_total: null,
      start_date: null,
      end_date: null,
      match_status: "inactive",
      match_reason:
        "„Marian Odchodzący” nie ma już aktywnej współpracy u tego klienta (kontrakt zakończony 12.02.2031). Zdecyduj: zostaw tę osobę na zamówieniu jako zapis historyczny, wznów współpracę, zastąp ją inną osobą albo usuń z zamówienia",
      contract: {
        contract_id: 12,
        candidate_id: 102,
        contractor_name: "Marian Odchodzący",
        status: "ended",
        start_date: "2030-01-01",
        end_date: "2031-02-12",
        rate_cost: 700,
        rate_cost_unit: "daily",
        rate_cost_currency: "PLN",
        rate_cost_rate_to_pln: 1,
        rate_cost_per_md_pln: 700,
      },
      options: [],
      nearest_names: [],
      warnings: [],
    },
  ],
};

function renderTab(onDone = vi.fn(), groups: OrderGroupRead[] = []) {
  vi.mocked(orderGroupsApi.list).mockResolvedValue({
    data: {
      groups,
      total_groups: groups.length,
      total_consultants: 0,
      suggested_order_type: "cost",
    },
  } as never);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MultiConsultantOrdersTab clientId={7} orderMailDocId={42} onOrderMailDocDone={onDone} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return onDone;
}

// Okno „Uzupełnij zamówienie" otwiera się dopiero po ŁAŃCUCHU trzech obietnic:
// `orderTarget` → pobranie PDF-a → `extractPlan`. Domyślny budżet `findBy*` to
// 1 s na całość, więc na obciążonej maszynie (CI, równoległe shardy) ten test
// potrafił paść na czasie, a nie na zachowaniu. Jawny, hojny limit czeka na to
// samo, tylko dłużej — asercja nadal wymaga, żeby karta się pojawiła.
const CARD_TIMEOUT = { timeout: 10_000 } as const;

describe("dokument z maila rozstrzygany w oknie zamówienia", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchAuthenticatedBlob).mockResolvedValue(
      new Blob(["%PDF-1.7"], { type: "application/pdf" }),
    );
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({ data: PLAN } as never);
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: { options: [], total: 0 },
    } as never);
    vi.mocked(orderGroupsApi.replaceFile).mockResolvedValue({
      data: { ...GROUP, has_file: true },
    } as never);
    vi.mocked(orderMailApi.resolvedInOrder).mockResolvedValue({ data: {} } as never);
  });

  it("istniejące zamówienie: „Uzupełnij” z PDF-em, decyzja o osobie, dokument schodzi z kolejki", async () => {
    vi.mocked(orderMailApi.orderTarget).mockResolvedValue({
      data: {
        client_id: 7,
        order_group_id: 77,
        order_type: "cost",
        order_number: "SAP 4500000777",
        attachment_name: "zlecenie.pdf",
      },
    } as never);
    vi.mocked(orderGroupsApi.update).mockResolvedValue({ data: GROUP } as never);
    vi.mocked(orderGroupsApi.addLines).mockResolvedValue({ data: GROUP } as never);
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const onDone = renderTab(vi.fn(), [GROUP]);

    const card = await screen.findByRole(
      "article",
      { name: "Konsultant: Marian Odchodzący" },
      CARD_TIMEOUT,
    );
    expect(screen.getByText(/dokument #42/)).toBeInTheDocument();
    expect(fetchAuthenticatedBlob).toHaveBeenCalledWith("/api/order-mail/queue/42/file");
    const pdf = vi.mocked(orderGroupsApi.extractPlan).mock.calls[0][1];
    expect(pdf.name).toBe("zlecenie.pdf");

    await user.click(within(card).getByRole("button", { name: "Zostaw jako historię" }));
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() => expect(orderMailApi.resolvedInOrder).toHaveBeenCalledWith(42, 77));
    expect(orderGroupsApi.addLines).toHaveBeenCalledWith(7, 77, [
      expect.objectContaining({ contract_id: 12, historical: true, end_date: "2031-02-12" }),
    ]);
    expect(vi.mocked(orderGroupsApi.update).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(orderGroupsApi.addLines).mock.invocationCallOrder[0],
    );
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("zamówienie z własnym PDF-em: plik z maila bez zgody służy tylko do odczytu", async () => {
    vi.mocked(orderMailApi.orderTarget).mockResolvedValue({
      data: {
        client_id: 7,
        order_group_id: 77,
        order_type: "cost",
        order_number: "SAP 4500000777",
        attachment_name: "zlecenie.pdf",
      },
    } as never);
    const withFile = { ...GROUP, has_file: true, filename: "SAP 4500000777.pdf" };
    vi.mocked(orderGroupsApi.update).mockResolvedValue({ data: withFile } as never);
    vi.mocked(orderGroupsApi.addLines).mockResolvedValue({ data: withFile } as never);
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    renderTab(vi.fn(), [withFile as OrderGroupRead]);

    const card = await screen.findByRole(
      "article",
      { name: "Konsultant: Marian Odchodzący" },
      CARD_TIMEOUT,
    );
    expect(screen.getByLabelText(/Zastąp PDF tego zamówienia plikiem z maila/)).not.toBeChecked();
    await user.click(within(card).getByRole("button", { name: "Zostaw jako historię" }));
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() => expect(orderMailApi.resolvedInOrder).toHaveBeenCalledWith(42, 77));
    expect(orderGroupsApi.replaceFile).not.toHaveBeenCalled();
  });

  it("aktywacja pustego szkicu MD: najpierw osoby z dokumentu, potem aktywacja", async () => {
    const draftGroup = {
      ...GROUP,
      order_type: "md",
      is_cost_based: false,
      budget_amount: null,
      budget_remaining: null,
      budget_used: null,
      status: "draft",
      status_label: "Draft",
      md_budget_mode: "per_person",
      md_budget_mode_locked: false,
    } as unknown as OrderGroupRead;
    vi.mocked(orderMailApi.orderTarget).mockResolvedValue({
      data: {
        client_id: 7,
        order_group_id: 77,
        order_type: "md",
        order_number: "SAP 4500000777",
        attachment_name: "zlecenie.pdf",
      },
    } as never);
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: {
        ...PLAN,
        total_value: null,
        lines: [
          {
            ...PLAN.lines[0],
            document_name: "Ewa Nowa",
            md_total: 20,
            match_status: "auto",
            match_reason: "Zapis identyczny z dokumentem",
            contract: { ...PLAN.lines[0].contract!, contract_id: 31, status: "active", end_date: null, contractor_name: "Ewa Nowa" },
          },
        ],
      },
    } as never);
    vi.mocked(orderGroupsApi.update).mockResolvedValue({ data: draftGroup } as never);
    vi.mocked(orderGroupsApi.addLines).mockResolvedValue({ data: draftGroup } as never);
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    renderTab(vi.fn(), [draftGroup]);

    await screen.findByRole(
      "article",
      { name: "Konsultant: Ewa Nowa" },
      CARD_TIMEOUT,
    );
    await user.selectOptions(screen.getByLabelText("Status zamówienia"), "active");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() => expect(orderGroupsApi.update).toHaveBeenCalledTimes(2));
    const [first, second] = vi.mocked(orderGroupsApi.update).mock.calls;
    expect(first[2]).not.toHaveProperty("status");
    expect(second[2]).toEqual({ status: "active" });
    const order = [
      vi.mocked(orderGroupsApi.update).mock.invocationCallOrder[0],
      vi.mocked(orderGroupsApi.addLines).mock.invocationCallOrder[0],
      vi.mocked(orderGroupsApi.update).mock.invocationCallOrder[1],
    ];
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });

  it("dopisanie osób nie weszło: okno zostaje otwarte, dokument dalej czeka", async () => {
    vi.mocked(orderMailApi.orderTarget).mockResolvedValue({
      data: {
        client_id: 7,
        order_group_id: 77,
        order_type: "cost",
        order_number: "SAP 4500000777",
        attachment_name: "zlecenie.pdf",
      },
    } as never);
    vi.mocked(orderGroupsApi.update).mockResolvedValue({ data: GROUP } as never);
    vi.mocked(orderGroupsApi.addLines).mockRejectedValue({
      response: { data: { detail: "Zamówienie jest zakończone." } },
    });
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    renderTab(vi.fn(), [GROUP]);

    const card = await screen.findByRole(
      "article",
      { name: "Konsultant: Marian Odchodzący" },
      CARD_TIMEOUT,
    );
    await user.click(within(card).getByRole("button", { name: "Zostaw jako historię" }));
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(
      await screen.findByText(/osób z dokumentu nie dopisano: Zamówienie jest zakończone/),
    ).toBeInTheDocument();
    expect(orderMailApi.resolvedInOrder).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeInTheDocument();
  });

  it("nowe zamówienie: okno „Nowe zamówienie” z PDF-em z maila", async () => {
    vi.mocked(orderMailApi.orderTarget).mockResolvedValue({
      data: {
        client_id: 7,
        order_group_id: null,
        order_type: "cost",
        order_number: "SAP 4500000777",
        attachment_name: "zlecenie.pdf",
      },
    } as never);
    renderTab();
    expect(
      await screen.findByRole(
        "article",
        { name: "Konsultant: Marian Odchodzący" },
        CARD_TIMEOUT,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Utwórz zamówienie" })).toBeInTheDocument();
  });

  it("dokument innego klienta nie otwiera okna", async () => {
    vi.mocked(orderMailApi.orderTarget).mockResolvedValue({
      data: {
        client_id: 999,
        order_group_id: null,
        order_type: "md",
        order_number: "1",
        attachment_name: null,
      },
    } as never);
    const onDone = renderTab();
    expect(await screen.findByText(/dotyczy innego klienta/)).toBeInTheDocument();
    expect(onDone).toHaveBeenCalled();
    expect(fetchAuthenticatedBlob).not.toHaveBeenCalled();
  });
});
