import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExtendOrderDialog } from "@/components/ExtendOrderDialog";
import { ToastProvider } from "@/components/Toast";
import {
  dlPortalApi,
  type ContractWithOrdersRead,
} from "@/lib/api/dlPortal";
import { useAuthStore, type User } from "@/store/auth";

vi.mock("@/lib/api/dlPortal", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/dlPortal")>();
  return {
    ...actual,
    dlPortalApi: {
      ...actual.dlPortalApi,
      createOrderExtension: vi.fn(),
    },
  };
});

const createOrderExtension = vi.mocked(dlPortalApi.createOrderExtension);

function user(role: "admin" | "delivery_lead"): User {
  return {
    id: role === "admin" ? 1 : 17,
    email: `${role}@example.com`,
    name: role,
    role,
    roles: [role],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    capabilities: role === "admin" ? ["manage_finance"] : ["view_client_operations"],
  };
}

const contract: ContractWithOrdersRead = {
  contract_id: 101,
  candidate_id: 7,
  candidate_name: "Jan Kowalski",
  contract_status: "active",
  contract_start_date: "2026-01-01",
  contract_end_date: null,
  // Intentionally populated to prove the UI does not trust a stale/leaky cache.
  rate_candidate: 12_000,
  initial_job_id: 44,
  initial_job_title: "Backend Engineer",
  latest_order_id: null,
  latest_order_end_date: null,
  latest_order_rate_client: 18_000,
  latest_order_monthly_margin: 6_000,
  days_to_latest_end: null,
  orders: [],
};

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ExtendOrderDialog
          clientId={10}
          contract={contract}
          onClose={vi.fn()}
          onCreated={vi.fn()}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("ExtendOrderDialog candidate finance lockdown", () => {
  beforeEach(() => {
    createOrderExtension.mockReset();
    createOrderExtension.mockResolvedValue({ data: {} } as never);
  });

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, hydrated: true });
    });
  });

  it("Delivery Lead nie widzi kwot i nie wysyła ich w FormData", async () => {
    act(() => {
      useAuthStore.setState({ user: user("delivery_lead"), hydrated: true });
    });
    renderDialog();

    expect(screen.queryByText(/Klient płaci/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Total value/)).not.toBeInTheDocument();
    expect(screen.queryByText(/marża/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Zapisz przedłużenie" }));

    await waitFor(() => expect(createOrderExtension).toHaveBeenCalledOnce());
    const formData = createOrderExtension.mock.calls[0][1];
    expect(formData.has("rate_client")).toBe(false);
    expect(formData.has("total_value")).toBe(false);
    expect(formData.get("contract_id")).toBe("101");
  });

  it("Admin z manage_finance widzi pola finansowe", () => {
    act(() => {
      useAuthStore.setState({ user: user("admin"), hydrated: true });
    });
    renderDialog();

    expect(screen.getByText(/Klient płaci/)).toBeInTheDocument();
    expect(screen.getByText(/Total value/)).toBeInTheDocument();
    expect(screen.getByText(/marża/i)).toBeInTheDocument();
  });
});
