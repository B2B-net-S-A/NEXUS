import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExtendOrderGroupModal } from "@/components/client-profile/orders/ExtendOrderGroupModal";
import { SwapConsultantModal } from "@/components/client-profile/orders/SwapConsultantModal";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    extractOrderPdf: vi.fn(),
    listActiveContractsForExtension: vi.fn(),
  },
}));

import { dlPortalApi } from "@/lib/api/dlPortal";

const LINE: OrderLineRead = {
  id: 1,
  group_id: 10,
  contract_id: 100,
  candidate_id: 5,
  consultant_name: "Jan Kowalski",
  job_id: null,
  job_title: null,
  status: "active",
  is_active: true,
  start_date: "2026-01-01",
  end_date: null,
  rate_cost: 1000,
  rate_revenue: 1200,
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
};

const SHARED_MD_GROUP: OrderGroupRead = {
  id: 10,
  client_id: 38339,
  order_number: "CP-MD-1",
  start_date: "2026-01-01",
  end_date: "2026-08-31",
  notes: null,
  created_at: "2026-01-01T10:00:00Z",
  status: "active",
  status_label: "Aktywne",
  closure_date: null,
  closure_reason: null,
  is_cost_based: false,
  is_md_budget_based: true,
  budget_amount: null,
  budget_used: null,
  budget_remaining: null,
  budget_manual_adjustment: null,
  md_budget_total: 100,
  md_budget_used: 30,
  md_budget_remaining: 70,
  md_budget_manual_adjustment: 0,
  predecessor_group_id: null,
  filename: null,
  has_file: false,
  content_type: null,
  size_bytes: null,
  file_uploaded_at: null,
  can_add_consultant: true,
  lines: [LINE],
  active_consultants: 1,
  event_count: 0,
  future_orders: [],
};

function provider(children: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>,
  );
}

describe("modale wspólnego budżetu MD", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(dlPortalApi.listActiveContractsForExtension).mockResolvedValue({
      data: [],
    } as never);
  });

  it("zamiana konsultanta pozostawia wspólną pulę bez przeliczenia per linia", () => {
    provider(
      <SwapConsultantModal
        open
        onOpenChange={vi.fn()}
        clientId={38339}
        group={SHARED_MD_GROUP}
        line={LINE}
        submitting={false}
        error={null}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByText("Zamówienie na MD")).toBeInTheDocument();
    expect(
      screen.getByText(/Pula MD jest wspólna dla całego zamówienia/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/pozostało.*MD/)).not.toBeInTheDocument();
    expect(screen.queryByText("Przeliczenie MD")).not.toBeInTheDocument();
  });

  it("przedłużenie wymaga nowej puli grupy i nie wysyła MD przy linii", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    provider(
      <ExtendOrderGroupModal
        open
        onOpenChange={vi.fn()}
        clientId={38339}
        group={SHARED_MD_GROUP}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
      />,
    );

    expect(screen.getByLabelText("Budżet w MD *")).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Liczba MD — Jan Kowalski"),
    ).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Numer zamówienia *"), "CP-MD-2");
    await user.type(screen.getByLabelText("Budżet w MD *"), "150,5");
    await user.click(screen.getByRole("button", { name: "Utwórz przedłużenie" }));

    expect(onSubmit).toHaveBeenCalledWith(
      {
        order_number: "CP-MD-2",
        start_date: "2026-09-01",
        end_date: null,
        notes: null,
        md_budget_total: 150.5,
        lines: [
          {
            contract_id: 100,
            rate_cost: 1000,
            rate_revenue: 1200,
            start_date: "2026-09-01",
            end_date: null,
          },
        ],
      },
      null,
    );
  });

  it("dotychczasowe zamówienie MD nadal budżetuje każdą linię osobno", () => {
    provider(
      <ExtendOrderGroupModal
        open
        onOpenChange={vi.fn()}
        clientId={38339}
        group={{
          ...SHARED_MD_GROUP,
          is_md_budget_based: false,
          md_budget_total: null,
          md_budget_used: null,
          md_budget_remaining: null,
          md_budget_manual_adjustment: null,
          lines: [{ ...LINE, input_mode: "md", input_value: 50, md_total: 50 }],
        }}
        submitting={false}
        error={null}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Liczba MD — Jan Kowalski")).toBeInTheDocument();
    expect(screen.queryByLabelText("Budżet w MD *")).not.toBeInTheDocument();
  });
});
