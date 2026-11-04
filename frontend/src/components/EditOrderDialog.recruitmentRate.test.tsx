import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditOrderDialog } from "@/components/EditOrderDialog";
import { ToastProvider } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { ClientOrderRead } from "@/lib/api/dlPortal";
import type { RecruitmentRate } from "@/lib/api/recruitmentRates";

vi.mock("@/lib/api/dlPortal", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/dlPortal")>();
  return {
    ...actual,
    dlPortalApi: { ...actual.dlPortalApi, updateOrder: vi.fn() },
  };
});

const updateOrder = vi.mocked(dlPortalApi.updateOrder);

const ORDER: ClientOrderRead = {
  id: 41,
  client_id: 10,
  contract_id: 101,
  job_id: null,
  framework_contract_id: null,
  title: "ZAM-41",
  description: null,
  status: "draft",
  order_type: "periodic",
  start_date: null,
  end_date: null,
  rate_candidate: 140,
  rate_client: 160,
  rate_unit: "hourly",
  total_value: null,
  md_quantity: null,
  currency: "PLN",
  project_part: null,
  filename: null,
  has_file: false,
  content_type: null,
  size_bytes: null,
  created_by_user_id: null,
  notes: null,
  created_at: "2026-10-01T10:00:00Z",
  updated_at: "2026-10-01T10:00:00Z",
  candidate_id: 1,
  candidate_name: "Jan Testowy",
  contract_status: "active",
  job_title: null,
  monthly_margin: null,
  days_to_end: null,
} as ClientOrderRead;

const RATES: RecruitmentRate = {
  candidate_id: 1,
  job_id: 7,
  job_title: "Java Developer",
  client_rate_value: "165.00",
  client_rate_unit: "hourly",
  client_rate_currency: "PLN",
  client_rate_at: "2026-10-03T09:00:00Z",
  client_rate_by_name: "Anna Lead",
  client_rate_redacted: false,
  candidate_rate_value: "140.00",
  candidate_rate_unit: "hourly",
  candidate_rate_currency: "PLN",
  candidate_rate_at: "2026-10-01T09:00:00Z",
};

function renderDialog(recruitmentRates: RecruitmentRate | null) {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <EditOrderDialog
          clientId={10}
          candidateId={1}
          order={ORDER}
          rateCandidate={null}
          contractRateUnit="hourly"
          canManageFinance
          recruitmentRates={recruitmentRates}
          onClose={vi.fn()}
          onSaved={vi.fn()}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("EditOrderDialog — stawki z rekrutacji (D7)", () => {
  beforeEach(() => {
    updateOrder.mockReset();
    updateOrder.mockResolvedValue({ data: {} } as never);
  });

  it("pokazuje linię z rekrutacji i notkę przy różnicy, a zapis przechodzi", async () => {
    const user = userEvent.setup();
    renderDialog(RATES);

    expect(
      screen.getByText(
        /Z rekrutacji „Java Developer” \(Anna Lead, .*\): 165 zł\/h · kandydat 140 zł\/h/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Stawka przychodowa różni się od stawki do klienta z rekrutacji/),
    ).toBeInTheDocument();
    // Koszt zgodny ze stawką kandydata — bez drugiej notki.
    expect(
      screen.queryByText(/Stawka kosztowa różni się/),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(updateOrder).toHaveBeenCalledOnce());
  });

  it("bez stawek z rekrutacji nic nie dokłada", () => {
    renderDialog(null);
    expect(screen.queryByTestId("recruitment-rate-hint")).not.toBeInTheDocument();
  });
});
