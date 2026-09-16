/**
 * „Uzupełnij zamówienie" z PDF-a (ticket 09.2026 — reguła ogólna dla zamówień
 * MD i kosztowych). Ten sam odczyt i to samo dopasowanie osób co „Nowe
 * zamówienie": osoba już na zamówieniu nie dostaje drugiej karty, a osoba
 * z zakończoną współpracą albo nieznaleziona dostaje jasny komunikat i wybór
 * zostaw / wznów / zastąp / usuń — nigdy cichy błąd ani pominięcie.
 *
 * Nazwiska i kwoty zmyślone (repo publiczne).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrderGroupFormModal } from "@/components/client-profile/orders/OrderGroupFormModal";
import type {
  OrderGroupExtraction,
  OrderGroupRead,
  OrderLineRead,
  OrderPlanContract,
  OrderPlanLine,
} from "@/lib/api/orderGroups";
import { orderGroupsApi } from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {
    extractPlan: vi.fn(),
    consultantOptions: vi.fn(),
  },
}));

function contract(overrides: Partial<OrderPlanContract> = {}): OrderPlanContract {
  return {
    contract_id: 11,
    candidate_id: 101,
    contractor_name: "Ewa Obecna",
    status: "active",
    start_date: "2031-01-01",
    end_date: null,
    rate_cost: 700,
    rate_cost_unit: "daily",
    rate_cost_currency: "PLN",
    rate_cost_rate_to_pln: 1,
    rate_cost_per_md_pln: 700,
    ...overrides,
  };
}

function planLine(overrides: Partial<OrderPlanLine> = {}): OrderPlanLine {
  return {
    ordinal: 1,
    document_name: "Ewa Obecna",
    position_label: null,
    rate_revenue: 840,
    rate_revenue_unit: "day",
    rate_revenue_gross: null,
    md_total: null,
    start_date: null,
    end_date: null,
    match_status: "auto",
    match_reason: "Zapis identyczny z dokumentem",
    contract: contract(),
    options: [],
    nearest_names: [],
    warnings: [],
    ...overrides,
  };
}

const PLAN: OrderGroupExtraction = {
  order_number: "SAP 4500000777",
  // Nagłówek zgodny z zamówieniem — bez pytania o rozbieżność pól.
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
    planLine(),
    planLine({
      ordinal: 2,
      document_name: "Marian Odchodzący",
      rate_revenue: 1280,
      match_status: "inactive",
      match_reason:
        "„Marian Odchodzący” nie ma już aktywnej współpracy u tego klienta (kontrakt zakończony 12.02.2031). Zdecyduj: zostaw tę osobę na zamówieniu jako zapis historyczny, wznów współpracę, zastąp ją inną osobą albo usuń z zamówienia",
      contract: contract({
        contract_id: 12,
        candidate_id: 102,
        contractor_name: "Marian Odchodzący",
        status: "ended",
        end_date: "2031-02-12",
      }),
    }),
    planLine({
      ordinal: 3,
      document_name: "Nikt Nieznany",
      match_status: "none",
      match_reason:
        "Nie znaleziono „Nikt Nieznany” w systemie — brak kontraktu z tym imieniem i nazwiskiem u tego klienta",
      contract: null,
    }),
  ],
};

function orderLine(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 1,
    group_id: 9,
    contract_id: 11,
    candidate_id: 101,
    consultant_name: "Ewa Obecna",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2031-01-01",
    end_date: null,
    rate_cost: 700,
    rate_revenue: 840,
    input_value: null,
    input_mode: null,
    md_total: null,
    md_remaining: null,
    md_manual_adjustment: null,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    md_optional_total: null,
    md_base_used: null,
    md_optional_used: null,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
    ...overrides,
  };
}

const GROUP: OrderGroupRead = {
  id: 9,
  client_id: 15,
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
  lines: [orderLine()],
  active_consultants: 1,
  event_count: 0,
  future_orders: [],
} as OrderGroupRead;

function renderModal(props: Partial<Parameters<typeof OrderGroupFormModal>[0]> = {}) {
  const onSubmit = vi.fn();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <OrderGroupFormModal
        open
        onOpenChange={vi.fn()}
        group={GROUP}
        clientId={15}
        orderType="cost"
        onOrderTypeChange={vi.fn()}
        allowedOrderTypes={["periodic", "cost", "md"]}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
        onDeleteFile={vi.fn()}
        {...props}
      />
    </QueryClientProvider>,
  );
  return onSubmit;
}

const PDF = new File(["%PDF-1.7"], "zlecenie.pdf", { type: "application/pdf" });

describe("Uzupełnij zamówienie — osoby z PDF-a spoza zamówienia", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({ data: PLAN } as never);
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: { options: [], total: 0 },
    } as never);
  });

  it("osoba z zakończoną współpracą: komunikat, wybór i zapis historyczny", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const onSubmit = renderModal();
    await user.upload(screen.getByLabelText(/Zamień plik PDF/), PDF);
    await user.click(screen.getByRole("button", { name: /Zczytaj dane z dokumentu/ }));

    // Osoba już na zamówieniu — bez drugiej karty.
    expect(await screen.findByText(/Już na zamówieniu \(1\)/)).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Konsultant: Ewa Obecna" })).toBeNull();

    // Osoba z zakończoną współpracą — ten sam komunikat i wybór co w „Nowe zamówienie".
    const ended = screen.getByRole("article", { name: "Konsultant: Marian Odchodzący" });
    expect(within(ended).getByText(/nie ma już aktywnej współpracy/)).toBeInTheDocument();
    for (const choice of [
      "Zostaw jako historię",
      "Wznów współpracę",
      "Zastąp kimś innym",
      "Usuń z zamówienia",
    ]) {
      expect(within(ended).getByRole("button", { name: choice })).toBeInTheDocument();
    }

    // Nieznaleziona — jasny komunikat, zastąp / usuń, nigdy cisza.
    const unknown = screen.getByRole("article", { name: "Konsultant: Nikt Nieznany" });
    expect(within(unknown).getByText(/Nie znaleziono „Nikt Nieznany” w systemie/)).toBeInTheDocument();
    expect(within(unknown).getByRole("button", { name: "Zastąp kimś innym" })).toBeInTheDocument();

    // Dopóki nie ma decyzji, zapis jest zablokowany.
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();

    await user.click(within(ended).getByRole("button", { name: "Zostaw jako historię" }));
    await user.click(within(unknown).getByRole("button", { name: "Usuń z zamówienia" }));
    const save = screen.getByRole("button", { name: "Zapisz" });
    await waitFor(() => expect(save).toBeEnabled());
    await user.click(save);

    const [values] = onSubmit.mock.calls[0];
    expect(values.lines).toEqual([
      expect.objectContaining({
        contract_id: 12,
        historical: true,
        end_date: "2031-02-12",
        document_name: "Marian Odchodzący",
      }),
    ]);
  });

  it("osoba wskazana ręcznie, która już jest na zamówieniu, nie zostanie dopisana drugi raz", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: {
        ...PLAN,
        lines: [
          planLine({
            document_name: "Ewa Obecna-Literówka",
            match_status: "ambiguous",
            match_reason: "Znaleziono 2 różne osoby o tym imieniu i nazwisku",
            contract: null,
            options: [contract(), contract({ contract_id: 13, candidate_id: 103 })],
          }),
        ],
      },
    } as never);
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    renderModal();
    await user.upload(screen.getByLabelText(/Zamień plik PDF/), PDF);
    await user.click(screen.getByRole("button", { name: /Zczytaj dane z dokumentu/ }));
    const card = await screen.findByRole("article", {
      name: "Konsultant: Ewa Obecna-Literówka",
    });
    // Pierwsza opcja to kontrakt 11 — ta osoba już pracuje na zamówieniu.
    await user.click(within(card).getAllByRole("button", { name: /kontrakt #11/ })[0]);
    expect(within(card).getByText(/ta osoba jest już na zamówieniu/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();
  });

  it("dokument bez nazwiska (sam numer ID konsultanta) nie tworzy karty do dopisania", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: {
        ...PLAN,
        consultant_ref: "K-0042",
        lines: [planLine({ document_name: null, match_status: "none", contract: null })],
      },
    } as never);
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    renderModal();
    await user.upload(screen.getByLabelText(/Zamień plik PDF/), PDF);
    await user.click(screen.getByRole("button", { name: /Zczytaj dane z dokumentu/ }));
    expect(await screen.findByText(/Numer ID konsultanta z dokumentu/)).toBeInTheDocument();
    expect(screen.queryByRole("article")).toBeNull();
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeEnabled();
  });

  it("PDF z kolejki maila jest odczytywany sam, z informacją o źródle", async () => {
    renderModal({
      autoReadFile: PDF,
      sourceNotice: "PDF z kolejki zamówień z maila (dokument #5).",
    });
    expect(screen.getByText(/dokument #5/)).toBeInTheDocument();
    await waitFor(() => expect(orderGroupsApi.extractPlan).toHaveBeenCalledTimes(1));
    expect(vi.mocked(orderGroupsApi.extractPlan).mock.calls[0][1]).toBe(PDF);
    expect(
      await screen.findByRole("article", { name: "Konsultant: Marian Odchodzący" }),
    ).toBeInTheDocument();
  });
});
