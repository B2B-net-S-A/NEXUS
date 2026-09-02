import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MaterialsTab } from "@/app/clients/[id]/MaterialsTab";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => mocks.get(...args),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MaterialsTab clientId={7} readOnly showContractTerms={false} />
    </QueryClientProvider>,
  );
}

describe("MaterialsTab read-only Delivery access", () => {
  it("keeps safe reads but hides every mutation and legal terms", async () => {
    mocks.get.mockResolvedValue({ data: [] });

    renderTab();

    expect(screen.queryByRole("button", { name: "Dodaj" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Warunki kontraktowe" }),
    ).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Wymagane dokumenty" }),
    );

    expect(await screen.findByText("Brak wymaganych dokumentów.")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Z szablonu/ })).toBeNull();
  });
});
