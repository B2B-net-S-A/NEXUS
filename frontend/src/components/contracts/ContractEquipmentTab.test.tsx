import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContractEquipmentTab } from "./ContractEquipmentTab";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  contractEquipmentApi: {
    list: mocks.list,
    create: mocks.create,
    update: mocks.update,
    delete: mocks.remove,
  },
}));

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ContractEquipmentTab contractId={42} readOnly />
    </QueryClientProvider>,
  );
}

describe("ContractEquipmentTab — read-only", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({
      data: [
        {
          id: 3,
          item_type: "laptop",
          owner: "ours",
          brand_model: "ThinkPad",
          serial_number: "ABC-123",
          handed_over_date: "2026-08-01",
          return_due_date: "2026-09-01",
          returned_date: null,
          return_status: "pending",
          description: null,
        },
      ],
    });
  });

  it("pokazuje sprzęt bez akcji dodania, zwrotu i usunięcia", async () => {
    renderTab();

    expect(await screen.findByText("ThinkPad")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj sprzęt/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zwrócono/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Akcje")).not.toBeInTheDocument();
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.update).not.toHaveBeenCalled();
    expect(mocks.remove).not.toHaveBeenCalled();
  });
});
