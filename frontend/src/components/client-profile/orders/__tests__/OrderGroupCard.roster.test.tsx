import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OrderGroupCard } from "@/components/client-profile/orders/OrderGroupCard";
import type {
  OrderGroupRead,
  OrderLineRead,
  OrderOffboardingCaseRead,
} from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: { events: vi.fn() },
}));

function line(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 1,
    group_id: 15,
    contract_id: 100,
    candidate_id: 5,
    consultant_name: "Michał Leśniak",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2026-05-01",
    end_date: null,
    rate_cost: 1000,
    rate_revenue: 1200,
    input_value: 50,
    input_mode: "md",
    md_total: 50,
    md_remaining: 30,
    md_manual_adjustment: 0,
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

function offboardingCase(
  overrides: Partial<OrderOffboardingCaseRead> = {},
): OrderOffboardingCaseRead {
  return {
    id: 7,
    contract_id: 100,
    order_id: 2,
    order_group_id: 15,
    client_id: 18,
    effective_date: "2026-08-31",
    status: "pending",
    version: 1,
    uses_shared_md_pool: false,
    remaining_md_snapshot: 20,
    rate_cost_snapshot: 1000,
    rate_revenue_snapshot: 1200,
    currency_snapshot: "PLN",
    order_number_snapshot: "4500030067",
    resolution: null,
    target_order_id: null,
    rate_basis: null,
    resolution_payload: null,
    resolved_at: null,
    resolved_by_user_id: null,
    created_by_user_id: null,
    created_at: "2026-08-31T10:00:00Z",
    updated_at: "2026-08-31T10:00:00Z",
    ...overrides,
  };
}

function group(overrides: Partial<OrderGroupRead> = {}): OrderGroupRead {
  return {
    id: 15,
    client_id: 18,
    order_number: "4500030067",
    start_date: "2026-05-01",
    end_date: null,
    notes: null,
    created_at: "2026-05-01T10:00:00Z",
    status: "active",
    status_label: "Aktywne",
    closure_date: null,
    closure_reason: null,
    is_cost_based: false,
    is_md_budget_based: false,
    budget_amount: null,
    budget_used: null,
    budget_remaining: null,
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
    lines: [line()],
    active_consultants: 1,
    event_count: 2,
    future_orders: [],
    ...overrides,
  };
}

const noop = () => {};

function renderCard(next: OrderGroupRead) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <OrderGroupCard
        clientId={18}
        group={next}
        canManage
        canManageLifecycle
        onAddConsultant={noop}
        onEditGroup={noop}
        onEditLine={noop}
        onSwapLine={noop}
        onDeleteLine={noop}
        onResolveOffboarding={noop}
        onDeleteGroup={noop}
        onCloseGroup={noop}
        onReopenGroup={noop}
        onExtendGroup={noop}
        onFocusGroup={noop}
        focusRequest={null}
      />
    </QueryClientProvider>,
  );
}

function section(name: RegExp) {
  return screen.getByRole("region", { name });
}

describe("OrderGroupCard — podział obsady", () => {
  it("zakończony konsultant z nierozstrzygniętą sprawą jest w „Zakończone”, nie w obsadzie", () => {
    // Do 09.2026 sprawa `pending` przypinała wiersz do „Aktywnej obsady”, żeby
    // decyzja DL nie zginęła — przez co sekcja odpowiadała na dwa pytania
    // naraz, a zespół czytał ją jako listę pracujących.
    const body = group({
      lines: [
        line(),
        line({
          id: 2,
          consultant_name: "Anna Zejście",
          status: "completed",
          is_active: false,
          end_date: "2026-08-31",
          cooperation_ended_on: "2026-08-31",
          md_used: 25,
          offboarding_case: offboardingCase(),
        }),
      ],
      active_consultants: 1,
    });

    renderCard(body);

    const active = section(/Aktywna obsada/);
    expect(within(active).getByText("Michał Leśniak")).toBeInTheDocument();
    expect(within(active).queryByText("Anna Zejście")).not.toBeInTheDocument();

    const completed = section(/Zakończone/);
    expect(within(completed).getByText("Anna Zejście")).toBeInTheDocument();
  });

  it("nagłówek „Zakończone” liczy sprawy czekające na decyzję", () => {
    // Przeniesienie wiersza nie może ukryć decyzji: licznik jest jedynym
    // sygnałem, że w tej sekcji zostało coś do zrobienia.
    const body = group({
      lines: [
        line(),
        line({
          id: 2,
          consultant_name: "Anna Zejście",
          status: "completed",
          is_active: false,
          cooperation_ended_on: "2026-08-31",
          offboarding_case: offboardingCase(),
        }),
        line({
          id: 3,
          consultant_name: "Piotr Historia",
          status: "completed",
          is_active: false,
          cooperation_ended_on: "2026-07-31",
          history_kept_at: "2026-08-01T09:00:00Z",
        }),
      ],
    });

    renderCard(body);

    // Ticket 6: nagłówek niesie liczbę osób i licznik decyzji, a sekcja
    // z decyzją do podjęcia jest domyślnie rozwinięta, karta z decyzją na górze.
    const heading = screen.getByRole("heading", {
      name: /Zakończone \(2\)\s*· 1 wymaga decyzji/,
    });
    expect(within(heading).getByRole("button")).toHaveAttribute("aria-expanded", "true");
    const cards = within(section(/Zakończone/)).getAllByRole("listitem");
    expect(cards[0]).toHaveTextContent("Anna Zejście");
    expect(cards[0]).toHaveTextContent("Podejmij decyzję");
    expect(cards[1]).toHaveTextContent("Zostawiony jako historia");
    expect(cards[1]).not.toHaveTextContent("Podejmij decyzję");
  });

  it("bez spraw do rozstrzygnięcia nagłówek zostaje sam „Zakończone”", () => {
    const body = group({
      lines: [
        line(),
        line({
          id: 2,
          consultant_name: "Piotr Historia",
          status: "completed",
          is_active: false,
          cooperation_ended_on: "2026-07-31",
          history_kept_at: "2026-08-01T09:00:00Z",
        }),
      ],
    });

    renderCard(body);

    // Nic nie czeka na decyzję — sekcja zwinięta, sam nagłówek z liczbą osób.
    const heading = screen.getByRole("heading", { name: /^Zakończone \(1\)$/ });
    expect(within(heading).getByRole("button")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Piotr Historia")).not.toBeInTheDocument();
  });

  it("następca, który kogoś zastąpił, zostaje w aktywnej obsadzie", () => {
    // Kryterium zgłoszenia: przenosimy zakończonych, nie zastępców.
    const body = group({
      lines: [
        line({
          id: 3,
          consultant_name: "Nowy Zastępca",
          predecessor_order_id: 2,
          predecessor_consultant_name: "Anna Zejście",
        }),
        line({
          id: 2,
          consultant_name: "Anna Zejście",
          status: "completed",
          is_active: false,
          cooperation_ended_on: "2026-08-31",
          replaced_by_order_id: 3,
          replaced_by_consultant_name: "Nowy Zastępca",
        }),
      ],
    });

    renderCard(body);

    const active = section(/Aktywna obsada/);
    expect(within(active).getByText("Nowy Zastępca")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Zakończone \(1\)/ }));
    const completed = section(/Zakończone/);
    expect(within(completed).getByText("Anna Zejście")).toBeInTheDocument();
  });
});
