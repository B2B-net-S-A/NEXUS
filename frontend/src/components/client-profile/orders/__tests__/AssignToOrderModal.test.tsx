import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AssignToOrderModal } from "@/components/client-profile/orders/AssignToOrderModal";
import type { ContractWithOrdersRead } from "@/lib/api/dlPortal";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";

const KAMILA = {
  contract_id: 645,
  candidate_id: 32903,
  candidate_name: "Kamila Gniewek",
  contract_status: "active",
  rate_candidate: 85,
  rate_unit: "hourly",
  initial_job_id: 4905,
  draft_card: true,
  orders: [],
} as unknown as ContractWithOrdersRead;

const KONRAD = {
  id: 672,
  contract_id: 403,
  consultant_name: "Konrad Sigda",
  status: "completed",
  is_active: false,
  rate_revenue: 800,
  md_total: 190,
  md_optional_total: 170,
  md_remaining: 187,
  pool_unit: "md",
  takeover_source: "ended",
  departure_date: "2026-08-31",
  offboarding_case: {
    id: 9,
    status: "pending",
    version: 1,
    remaining_md_snapshot: 187,
    uses_shared_md_pool: false,
  },
} as unknown as OrderLineRead;

const ACTIVE = {
  ...KONRAD,
  id: 673,
  contract_id: 404,
  consultant_name: "Jan Aktywny",
  status: "active",
  is_active: true,
  takeover_source: null,
  offboarding_case: null,
} as unknown as OrderLineRead;

const CEZ_242 = {
  id: 96,
  client_id: 115,
  order_number: "CeZ/242/2025",
  status: "active",
  is_cost_based: false,
  is_md_budget_based: false,
  md_budget_mode: "per_person",
  can_add_consultant: true,
  executive_contract: { id: 2, number: "CeZ/145/2025" },
  lines: [KONRAD, ACTIVE],
} as unknown as OrderGroupRead;

function renderModal(overrides: Partial<Parameters<typeof AssignToOrderModal>[0]> = {}) {
  const props = {
    open: true,
    onOpenChange: vi.fn(),
    contractor: KAMILA,
    groups: [CEZ_242],
    submitting: false,
    error: null,
    onJoin: vi.fn(),
    onTakeover: vi.fn(),
    onNewOrder: vi.fn(),
    ...overrides,
  };
  render(<AssignToOrderModal {...props} />);
  return props;
}

describe("Przypisz do zamówienia (CeZ)", () => {
  it("pokazuje trzy ścieżki", () => {
    renderModal();
    expect(screen.getByRole("button", { name: /Dołącz do aktywnego zamówienia/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Wejdź za konsultanta/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Nowe zamówienie/ })).toBeEnabled();
  });

  it("scenariusz z ticketu: Kamila wchodzi za Konrada od 01.09.2026", async () => {
    const props = renderModal();
    await userEvent.click(screen.getByRole("button", { name: /Wejdź za konsultanta/ }));
    const who = screen.getByLabelText(/Za kogo wchodzi/);
    expect(screen.queryByRole("option", { name: /Jan Aktywny/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(who, "672");
    expect(screen.getByLabelText(/Data wejścia/)).toHaveValue("2026-09-01");
    expect(screen.getByLabelText(/Stawka koszt/)).toHaveValue("680");
    expect(screen.getByText("Z kontraktu: 85 PLN/h × 8")).toBeInTheDocument();
    expect(screen.getByText(/przejmuje/)).toHaveTextContent("187 MD");
    await userEvent.type(screen.getByLabelText(/Stawka przychód/), "800");
    await userEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(props.onTakeover).toHaveBeenCalledWith(96, {
      contract_id: 645,
      departing_order_id: 672,
      entry_date: "2026-09-01",
      rate_cost: 680,
      rate_revenue: 800,
      md_transfer_method: "one_to_one",
      expected_case_version: 1,
    });
  });

  it("dołączenie ostrzega o MD ponad wolną pulę, ale pozwala zapisać", async () => {
    const props = renderModal();
    await userEvent.click(
      screen.getByRole("button", { name: /Dołącz do aktywnego zamówienia/ }),
    );
    await userEvent.selectOptions(screen.getByLabelText(/Zamówienie \*/), "96");
    await userEvent.type(screen.getByLabelText(/MD — podstawa/), "150");
    await userEvent.type(screen.getByLabelText(/MD — opcja/), "50");
    await userEvent.type(screen.getByLabelText(/Stawka przychód/), "800");
    expect(screen.getByText(/13 MD ponad wolną pulę zamówienia/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(props.onJoin).toHaveBeenCalledWith(
      96,
      expect.objectContaining({
        contract_id: 645,
        input_mode: "md",
        input_value: 150,
        optional_md: 50,
        rate_cost: 680,
        assignment: "join",
      }),
    );
  });

  it("nowe zamówienie otwiera dotychczasowe „Uzupełnij zamówienie”", async () => {
    const props = renderModal();
    await userEvent.click(screen.getByRole("button", { name: /Nowe zamówienie/ }));
    expect(props.onNewOrder).toHaveBeenCalled();
  });
});
