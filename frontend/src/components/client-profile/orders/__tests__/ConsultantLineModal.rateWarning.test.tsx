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

/** Konsultant wracający do klienta: stary kontrakt `ended` (500) i nowy
 *  `draft` (700), zero `active`/`ending`. Backend liczy obie flagi z innych
 *  zbiorów, więc ten stan jest osiągalny zwykłymi danymi:
 *  `suggested_rate_cost = null` PRZY `has_different_client_contract_rates`. */
const RETURNING: ConsultantOption = {
  candidate_id: 5,
  contract_id: 100,
  full_name: "Barbara Nowak",
  first_name: "Barbara",
  last_name: "Nowak",
  source: "client_recruitment",
  source_label: "Rekrutacja u klienta",
  job_title: "Analityk danych",
  suggested_rate_cost: null,
  has_different_client_contract_rates: true,
};

const GROUP: OrderGroupRead = {
  id: 10,
  client_id: 7,
  order_number: "445",
  start_date: "2026-03-01",
  end_date: null,
  notes: null,
  created_at: "2026-03-01T10:00:00Z",
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
        clientId={7}
        group={GROUP}
        submitting={false}
        error={null}
        onSubmit={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("ConsultantLineModal — ostrzeżenie o rozbieżnych stawkach", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("bez aktywnego kontraktu nie twierdzi, że stawkę wstawiono", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: { options: [RETURNING], total: 1 },
    } as never);
    renderModal();

    await user.click(await screen.findByRole("button", { name: /Barbara Nowak/ }));

    const warning = screen.getByRole("status");
    expect(warning).toHaveTextContent(/żaden nie jest aktywny/i);
    // Zdanie o wstawionej stawce jest tu FAŁSZEM — pole zostaje puste,
    // a operator, który mu uwierzy, pójdzie skopiować kwotę z kontraktu
    // historycznego, którego świadomie nie podpowiadamy.
    expect(warning).not.toHaveTextContent(/Wstawiono stawkę/i);
    expect(
      screen.getByRole("textbox", { name: /Stawka kosztowa/ }),
    ).toHaveValue("");
  });

  it("z aktywnym kontraktem zostawia komunikat o wstawionej stawce", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: {
        options: [{ ...RETURNING, suggested_rate_cost: 560 }],
        total: 1,
      },
    } as never);
    renderModal();

    await user.click(await screen.findByRole("button", { name: /Barbara Nowak/ }));

    const warning = screen.getByRole("status");
    expect(warning).toHaveTextContent(/Wstawiono stawkę z aktywnego kontraktu/i);
    expect(warning).not.toHaveTextContent(/żaden nie jest aktywny/i);
    expect(
      screen.getByRole("textbox", { name: /Stawka kosztowa/ }),
    ).toHaveValue("560");
  });
});
