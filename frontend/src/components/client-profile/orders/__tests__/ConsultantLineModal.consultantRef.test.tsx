import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConsultantLineModal } from "@/components/client-profile/orders/ConsultantLineModal";
import type { ConsultantOption, OrderGroupRead } from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: { consultantOptions: vi.fn() },
  mdConsumptionApi: {},
}));

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: { extractOrderPdf: vi.fn() },
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";
import { dlPortalApi } from "@/lib/api/dlPortal";

const CONSULTANT: ConsultantOption = {
  candidate_id: 5,
  contract_id: 100,
  full_name: "Damian Krawczyk",
  first_name: "Damian",
  last_name: "Krawczyk",
  source: "client_recruitment",
  source_label: "Rekrutacja u klienta",
  job_title: "Inżynier danych",
  suggested_rate_cost: 1000,
  has_different_client_contract_rates: false,
};

const GROUP: OrderGroupRead = {
  id: 10,
  client_id: 12,
  order_number: "3728_2026",
  start_date: "2026-08-01",
  end_date: null,
  notes: null,
  created_at: "2026-08-01T10:00:00Z",
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
  lines: [],
  active_consultants: 0,
  event_count: 0,
  future_orders: [],
};

function renderModal() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ConsultantLineModal
        open
        onOpenChange={vi.fn()}
        clientId={12}
        group={GROUP}
        submitting={false}
        error={null}
        onSubmit={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

/** PDF-y BNP nie zawierają imienia ani nazwiska — niosą wyłącznie numer ID
 *  konsultanta. To JEDYNY ślad tożsamości w dokumencie, więc musi dotrzeć do
 *  operatora dokładnie w tym widoku, w którym BNP pracuje (wielo-konsultanci).
 *  Pole dołożone do złego z dwóch widoków zamówień jest martwe. */
describe("ConsultantLineModal — numer ID konsultanta z dokumentu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: { options: [CONSULTANT], total: 1 },
    } as never);
  });

  it("pokazuje odczytany numer ID do potwierdzenia", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue({
      data: {
        title: "3728_2026",
        start_date: "2026-08-01",
        end_date: "2026-12-31",
        rate_client: 1040,
        rate_unit: "day",
        total_value: null,
        currency: "PLN",
        md_total: 105,
        uncertain: false,
        uncertain_reasons: [],
        fields_confidence: {},
        consultant_ref: "4711",
        source: "claude",
      },
    } as never);
    renderModal();

    await user.click(await screen.findByRole("button", { name: /Damian Krawczyk/ }));
    const input = document.querySelector<HTMLInputElement>("#line-po");
    expect(input).not.toBeNull();
    await user.upload(
      input as HTMLInputElement,
      new File([new Uint8Array([1, 2, 3])], "bnp.pdf", {
        type: "application/pdf",
      }),
    );
    await user.click(
      await screen.findByRole("button", { name: /Zczytaj dane z dokumentu/ }),
    );

    expect(await screen.findByText(/Numer ID konsultanta/)).toBeInTheDocument();
    expect(await screen.findByText("4711")).toBeInTheDocument();
  });

  it("bez numeru w dokumencie nie pokazuje pustego komunikatu", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue({
      data: {
        title: "445",
        start_date: null,
        end_date: null,
        rate_client: null,
        rate_unit: null,
        total_value: null,
        currency: null,
        md_total: null,
        uncertain: false,
        uncertain_reasons: [],
        fields_confidence: {},
        source: "claude",
      },
    } as never);
    renderModal();

    await user.click(await screen.findByRole("button", { name: /Damian Krawczyk/ }));
    const input = document.querySelector<HTMLInputElement>("#line-po");
    await user.upload(
      input as HTMLInputElement,
      new File([new Uint8Array([1, 2, 3])], "inny.pdf", {
        type: "application/pdf",
      }),
    );
    await user.click(
      await screen.findByRole("button", { name: /Zczytaj dane z dokumentu/ }),
    );

    expect(screen.queryByText(/Numer ID konsultanta/)).not.toBeInTheDocument();
  });
});
