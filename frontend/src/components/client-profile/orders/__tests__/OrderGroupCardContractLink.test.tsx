import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OrderGroupCard } from "@/components/client-profile/orders/OrderGroupCard";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";

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
    md_remaining: 10,
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
    event_count: 0,
    future_orders: [],
    ...overrides,
  };
}

const noop = () => {};

function renderCard(value: OrderGroupRead) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <OrderGroupCard
        clientId={18}
        group={value}
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

describe("OrderGroupCard — nazwisko prowadzi do kontraktu z tego wiersza", () => {
  it("dwie osoby na jednym zamówieniu dostają DWA różne kontrakty", () => {
    renderCard(
      group({
        lines: [
          line({ id: 1, contract_id: 600, consultant_name: "Wojciech Sokolnicki" }),
          line({ id: 2, contract_id: 601, consultant_name: "Anna Michalczyk" }),
        ],
        active_consultants: 2,
      }),
    );

    // Sedno ticketu: adres bierze się z LINII, nie z osoby ani z zamówienia —
    // ta sama osoba u innego klienta ma inny kontrakt i nie wolno go zgadywać.
    expect(
      screen.getByRole("link", { name: "Wojciech Sokolnicki" }),
    ).toHaveAttribute("href", "/contracts/600");
    expect(
      screen.getByRole("link", { name: "Anna Michalczyk" }),
    ).toHaveAttribute("href", "/contracts/601");
  });

  it("linia z listy „Zakończone” też jest linkiem", () => {
    renderCard(
      group({
        lines: [
          line({ id: 1, contract_id: 600, consultant_name: "Wojciech Sokolnicki" }),
          line({
            id: 2,
            contract_id: 700,
            consultant_name: "Historyczny Konsultant",
            is_active: false,
            status: "completed",
            end_date: "2026-04-30",
          }),
        ],
      }),
    );

    expect(screen.getByRole("heading", { name: "Zakończone" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Historyczny Konsultant" }),
    ).toHaveAttribute("href", "/contracts/700");
  });

  it("linia przyszłego zamówienia też jest linkiem", () => {
    renderCard(
      group({
        future_orders: [
          group({
            id: 16,
            order_number: "4500029903",
            start_date: "2026-08-15",
            status: "scheduled",
            status_label: "Zaplanowane",
            lines: [
              line({
                id: 9,
                group_id: 16,
                contract_id: 800,
                consultant_name: "Przyszły Konsultant",
                status: "draft",
              }),
            ],
            active_consultants: 0,
            future_orders: [],
          }),
        ],
      }),
    );

    expect(
      screen.getByRole("link", { name: "Przyszły Konsultant" }),
    ).toHaveAttribute("href", "/contracts/800");
  });

  it("nazwą dostępną linku jest NAZWISKO, nie numer kontraktu", () => {
    renderCard(
      group({
        lines: [line({ id: 1, contract_id: 600, consultant_name: "Wojciech Sokolnicki" })],
      }),
    );

    const link = screen.getByRole("link", { name: "Wojciech Sokolnicki" });
    // Zmierzone w przeglądarce: `title` na kotwicy PRZEJMUJE nazwę w drzewie
    // dostępności Chrome — nazwisko znika, a czytnik ekranu czyta numer
    // kontraktu. jsdom liczy nazwę inaczej, więc samo `name:` wyżej tego nie
    // wyłapie; dlatego pytamy wprost o atrybuty.
    expect(link).not.toHaveAttribute("title");
    expect(link).not.toHaveAttribute("aria-label");
  });

  it("poprzednik i następca NIE są linkami do kontraktu", () => {
    renderCard(
      group({
        lines: [
          line({
            id: 1,
            contract_id: 600,
            consultant_name: "Wojciech Sokolnicki",
            predecessor_order_id: 41,
            predecessor_consultant_name: "Poprzedni Konsultant",
            replaced_by_order_id: 42,
            replaced_by_consultant_name: "Następny Konsultant",
          }),
        ],
      }),
    );

    // Te nazwiska niosą wyłącznie `*_order_id` — kontraktu nie da się z nich
    // wyprowadzić, więc link musiałby go zgadywać i trafiłby w cudzy kontrakt.
    expect(
      screen.queryByRole("link", { name: /Poprzedni Konsultant/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Następny Konsultant/ }),
    ).not.toBeInTheDocument();
  });
});
