import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OffboardingDecisionModal } from "@/components/client-profile/orders/OffboardingDecisionModal";
import type { ContractWithOrdersRead } from "@/lib/api/dlPortal";
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
  md_optional_total: null,
  md_base_used: null,
  md_optional_used: null,
  replaced_by_order_id: null,
  replaced_by_consultant_name: null,
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
    executive_contract: null,
    md_positions_total: null,
    md_used_total: null,
    contract_value_pln: null,
    used_value_pln: null,
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

const RECIPIENT: OrderLineRead = {
  ...LINE,
  id: 2,
  contract_id: 101,
  consultant_name: "Anna Nowak",
  status: "active",
  is_active: true,
  rate_revenue: 1000,
  offboarding_case: null,
};

const KAMILA = {
  contract_id: 645,
  candidate_id: 32903,
  candidate_name: "Kamila Gniewek",
  contract_status: "active",
  rate_candidate: 85,
  rate_unit: "hourly",
  draft_card: true,
  orders: [],
} as unknown as ContractWithOrdersRead;

describe("przejęcie pozostałych MD w decyzji (ticket 09.2026, B1/A5)", () => {
  it("pula w MD: komunikat 1:1 zamiast przelicznika i wysyłka one_to_one", async () => {
    const onSubmit = vi.fn();
    render(
      <OffboardingDecisionModal
        open
        onOpenChange={vi.fn()}
        group={group({ lines: [LINE, RECIPIENT] })}
        line={{ ...LINE, pool_unit: "md" }}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
      />,
    );
    await userEvent.click(
      screen.getByRole("radio", { name: /Przelicz na innego konsultanta/ }),
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/Konsultant przejmujący/),
      "line:2",
    );
    expect(screen.queryByText(/Przelicz po stawce/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/Zamówienie ma pulę w MD — Anna Nowak przejmuje/),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Zapisz decyzję" }));
    expect(onSubmit).toHaveBeenCalledWith({
      action: "transfer",
      target_order_id: 2,
      md_transfer_method: "one_to_one",
      expected_version: 1,
    });
  });

  it("pula w kwocie: zapis nieaktywny, dopóki DL nie wybierze opcji", async () => {
    const onSubmit = vi.fn();
    render(
      <OffboardingDecisionModal
        open
        onOpenChange={vi.fn()}
        group={group({ lines: [LINE, RECIPIENT] })}
        line={{ ...LINE, pool_unit: "amount" }}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
      />,
    );
    await userEvent.click(
      screen.getByRole("radio", { name: /Przelicz na innego konsultanta/ }),
    );
    await userEvent.selectOptions(
      screen.getByLabelText(/Konsultant przejmujący/),
      "line:2",
    );
    const save = screen.getByRole("button", { name: "Zapisz decyzję" });
    expect(save).toBeDisabled();
    // 90 MD × 1320 zł ÷ 1000 zł = 118,8 MD
    expect(screen.getByText("118,8 MD")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("radio", { name: /po stawce osoby przychodzącej/ }),
    );
    expect(save).toBeEnabled();
    await userEvent.click(save);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ md_transfer_method: "incoming_rate" }),
    );
  });

  it("nowa osoba ze szkiców wchodzi za odchodzącego (stawka z kontraktu × 8)", async () => {
    const onTakeover = vi.fn();
    render(
      <OffboardingDecisionModal
        open
        onOpenChange={vi.fn()}
        group={group()}
        line={{ ...LINE, pool_unit: "md" }}
        submitting={false}
        error={null}
        onSubmit={vi.fn()}
        newPeople={[KAMILA]}
        onTakeover={onTakeover}
      />,
    );
    await userEvent.click(
      screen.getByRole("radio", { name: /Przelicz na innego konsultanta/ }),
    );
    const select = screen.getByLabelText(/Konsultant przejmujący/);
    expect(
      screen.getByRole("group", { name: "Nowe osoby u klienta" }),
    ).toBeInTheDocument();
    await userEvent.selectOptions(select, "contract:645");
    expect(screen.getByText("Z kontraktu: 85 PLN/h × 8")).toBeInTheDocument();
    expect(screen.getByLabelText(/Stawka koszt/)).toHaveValue("680");
    expect(screen.getByLabelText(/Data wejścia/)).toHaveValue("2026-09-01");
    await userEvent.type(screen.getByLabelText(/Stawka przychód/), "800");
    await userEvent.click(screen.getByRole("button", { name: "Zapisz decyzję" }));
    expect(onTakeover).toHaveBeenCalledWith({
      contract_id: 645,
      departing_order_id: 1,
      entry_date: "2026-09-01",
      rate_cost: 680,
      rate_revenue: 800,
      md_transfer_method: "one_to_one",
      expected_case_version: 1,
    });
  });
});
