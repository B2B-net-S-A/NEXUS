import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OffboardingDecisionModal } from "@/components/client-profile/orders/OffboardingDecisionModal";
import type {
  OrderGroupRead,
  OrderLineRead,
  OrderOffboardingCaseRead,
} from "@/lib/api/orderGroups";

const CASE: OrderOffboardingCaseRead = {
  id: 77,
  contract_id: 100,
  order_id: 1,
  order_group_id: 10,
  client_id: 7,
  effective_date: "2026-08-31",
  status: "pending",
  version: 1,
  uses_shared_md_pool: false,
  remaining_md_snapshot: 90,
  rate_cost_snapshot: 1000,
  rate_revenue_snapshot: 1320,
  currency_snapshot: "PLN",
  order_number_snapshot: "3728_2026",
  resolution: null,
  target_order_id: null,
  rate_basis: null,
  resolution_payload: null,
  resolved_at: null,
  resolved_by_user_id: null,
  created_by_user_id: null,
  created_at: "2026-08-31T10:00:00Z",
  updated_at: "2026-08-31T10:00:00Z",
};

const LINE: OrderLineRead = {
  id: 1,
  group_id: 10,
  contract_id: 100,
  candidate_id: 5,
  consultant_name: "Tomasz Płonka",
  job_id: null,
  job_title: null,
  status: "completed",
  is_active: false,
  start_date: "2026-01-01",
  end_date: "2026-08-31",
  rate_cost: 1000,
  rate_revenue: 1320,
  input_value: 90,
  input_mode: "md",
  md_total: 90,
  md_remaining: 90,
  md_manual_adjustment: 0,
  predecessor_order_id: null,
  predecessor_consultant_name: null,
  invoiced_total: null,
  unsettled_total: null,
  missing_consumption_month: null,
  offboarding_case: CASE,
};

function group(overrides: Partial<OrderGroupRead> = {}): OrderGroupRead {
  return {
    id: 10,
    client_id: 7,
    order_number: "3728_2026",
    start_date: "2026-01-01",
    end_date: "2026-12-31",
    notes: null,
    created_at: "2026-01-01T10:00:00Z",
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
    lines: [LINE],
    active_consultants: 0,
    event_count: 0,
    future_orders: [],
    ...overrides,
  } as OrderGroupRead;
}

describe("decyzja po zakończeniu współpracy", () => {
  it("oferuje przywrócenie jako trzecią decyzję", () => {
    render(
      <OffboardingDecisionModal
        open
        onOpenChange={vi.fn()}
        group={group()}
        line={LINE}
        submitting={false}
        error={null}
        onSubmit={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("radio", { name: /Przywróć jako aktywne/ }),
    ).toBeInTheDocument();
  });

  it("wysyła datę zakończenia podpowiedzianą z okresu zamówienia", async () => {
    const onSubmit = vi.fn();
    render(
      <OffboardingDecisionModal
        open
        onOpenChange={vi.fn()}
        group={group()}
        line={LINE}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
      />,
    );

    await userEvent.click(
      screen.getByRole("radio", { name: /Przywróć jako aktywne/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Zapisz decyzję" }));

    expect(onSubmit).toHaveBeenCalledWith({
      action: "restore",
      restore_end_date: "2026-12-31",
      expected_version: 1,
    });
  });

  it("nie pozwala zapisać przywrócenia bez daty, gdy zamówienie ma koniec", async () => {
    // Pusta data znaczy „bezterminowo" — linia przeżywałaby własne
    // zamówienie. Serwer to odrzuca, więc formularz nie może na to pozwolić.
    const onSubmit = vi.fn();
    render(
      <OffboardingDecisionModal
        open
        onOpenChange={vi.fn()}
        group={group()}
        line={LINE}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
      />,
    );

    await userEvent.click(
      screen.getByRole("radio", { name: /Przywróć jako aktywne/ }),
    );
    await userEvent.clear(screen.getByLabelText(/Współpraca trwa do/));
    expect(screen.getByRole("button", { name: "Zapisz decyzję" })).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("zamówienie bezterminowe dopuszcza pustą datę", async () => {
    const onSubmit = vi.fn();
    render(
      <OffboardingDecisionModal
        open
        onOpenChange={vi.fn()}
        group={group({ end_date: null })}
        line={LINE}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
      />,
    );

    await userEvent.click(
      screen.getByRole("radio", { name: /Przywróć jako aktywne/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Zapisz decyzję" }));

    expect(onSubmit).toHaveBeenCalledWith({
      action: "restore",
      restore_end_date: null,
      expected_version: 1,
    });
  });

  it("usunięcie i przeniesienie działają jak dotąd", async () => {
    const onSubmit = vi.fn();
    render(
      <OffboardingDecisionModal
        open
        onOpenChange={vi.fn()}
        group={group()}
        line={LINE}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Zapisz decyzję" }));
    expect(onSubmit).toHaveBeenCalledWith({
      action: "remove",
      expected_version: 1,
    });
  });
});
