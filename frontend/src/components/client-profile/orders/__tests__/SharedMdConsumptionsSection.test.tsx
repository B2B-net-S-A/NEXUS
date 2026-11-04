import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SharedMdConsumptionsSection } from "@/components/client-profile/orders/SharedMdConsumptionsSection";
import type { SharedMdConsumptionsResponse } from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {
    listSharedMdConsumptions: vi.fn(),
    putSharedMdConsumption: vi.fn(),
    deleteSharedMdConsumption: vi.fn(),
  },
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

const GROUP = {
  id: 504,
  start_date: "2026-06-01",
  end_date: null,
  status: "active",
} as const;

const DATA: SharedMdConsumptionsResponse = {
  months: [
    {
      period_month: "2026-08",
      md_reported: 25,
      source: "manual",
      breakdown: [
        { order_id: 1, consultant_name: "Anna Przykładowa", md: 15 },
        { order_id: 2, consultant_name: "Bartosz Wzorcowy", md: 10 },
      ],
      breakdown_source: "manual",
      created_by_name: "Delivery Lead",
      updated_at: "2026-09-02T09:00:00Z",
    },
    {
      period_month: "2026-07",
      md_reported: 12,
      source: "manual",
      breakdown: null,
      breakdown_source: null,
      created_by_name: null,
      updated_at: null,
    },
  ],
  consultants: [
    { order_id: 1, consultant_name: "Anna Przykładowa", status: "active" },
    { order_id: 2, consultant_name: "Bartosz Wzorcowy", status: "active" },
  ],
  md_budget_total: 100,
  md_used: 37,
  md_remaining: 63,
};

function renderSection(canEdit = true) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SharedMdConsumptionsSection clientId={18} group={GROUP} canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(orderGroupsApi.listSharedMdConsumptions).mockReset();
  vi.mocked(orderGroupsApi.putSharedMdConsumption).mockReset();
  vi.mocked(orderGroupsApi.deleteSharedMdConsumption).mockReset();
  vi.mocked(orderGroupsApi.listSharedMdConsumptions).mockResolvedValue({
    data: DATA,
  } as never);
});

describe("SharedMdConsumptionsSection — zejścia wspólnej puli MD", () => {
  it("pokazuje miesiące z podziałem na osoby i zapis bez podziału", async () => {
    renderSection();
    expect(
      await screen.findByText("Anna Przykładowa: 15 MD · Bartosz Wzorcowy: 10 MD"),
    ).toBeInTheDocument();
    expect(screen.getByText("bez podziału na osoby")).toBeInTheDocument();
  });

  it("edycja zmienia MD konsultanta i zapisuje cały miesiąc", async () => {
    vi.mocked(orderGroupsApi.putSharedMdConsumption).mockResolvedValue({
      data: DATA,
    } as never);
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: /Edytuj zejście za sie/ }));

    const anna = screen.getByLabelText("Anna Przykładowa");
    expect(anna).toHaveValue("15");
    await user.clear(anna);
    await user.type(anna, "12,5");
    expect(screen.getByText(/Razem:/)).toHaveTextContent("22,5 MD");
    await user.click(screen.getByRole("button", { name: "Zapisz zejście" }));

    await waitFor(() =>
      expect(orderGroupsApi.putSharedMdConsumption).toHaveBeenCalledWith(18, 504, "2026-08", {
        lines: [
          { order_id: 1, md: 12.5 },
          { order_id: 2, md: 10 },
        ],
      }),
    );
  });

  it("miesiąc zapisany jako sama suma prosi o podział na osoby", async () => {
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: /Edytuj zejście za lip/ }));
    expect(screen.getByRole("status")).toHaveTextContent("sumę 12 MD bez podziału");
    expect(screen.getByRole("button", { name: "Zapisz zejście" })).toBeDisabled();
  });

  it("usunięcie miesiąca wymaga potwierdzenia", async () => {
    vi.mocked(orderGroupsApi.deleteSharedMdConsumption).mockResolvedValue({
      data: DATA,
    } as never);
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: /Usuń zejście za sie/ }));
    expect(orderGroupsApi.deleteSharedMdConsumption).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Potwierdź usunięcie" }));
    await waitFor(() =>
      expect(orderGroupsApi.deleteSharedMdConsumption).toHaveBeenCalledWith(18, 504, "2026-08"),
    );
  });

  it("bez uprawnień nie ma przycisków edycji", async () => {
    renderSection(false);
    await screen.findByText("bez podziału na osoby");
    expect(screen.queryByRole("button", { name: /Edytuj zejście/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj miesiąc/ })).not.toBeInTheDocument();
  });

  it("awaria pobrania nie udaje braku zejść", async () => {
    vi.mocked(orderGroupsApi.listSharedMdConsumptions).mockRejectedValue(new Error("boom"));
    renderSection();
    expect(
      await screen.findByText("Nie udało się wczytać zejść wspólnej puli MD."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Brak zejść MD na tym zamówieniu.")).not.toBeInTheDocument();
  });
});
