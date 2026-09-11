import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EventHistoryTab } from "./EventHistoryTab";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({ default: { get: mocks.get } }));

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <EventHistoryTab />
    </QueryClientProvider>,
  );
}

const LABELS = {
  entity_types: { client: "Klient", order: "Zamówienie" },
  event_types: { "client.delete": "Usunięcie klienta" },
  outcomes: { executed: "Wykonano", blocked: "Zablokowano" },
};

describe("EventHistoryTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("pokazuje kto, kiedy, co i z jakim wynikiem — także zablokowane próby", async () => {
    mocks.get.mockResolvedValue({
      data: {
        ...LABELS,
        total: 2,
        limit: 50,
        offset: 0,
        items: [
          {
            id: 2,
            occurred_at: "2026-09-11T08:30:00Z",
            event_type: "client.delete",
            event_label: "Usunięcie klienta",
            entity_type: "client",
            entity_type_label: "Klient",
            entity_id: 7,
            entity_label: "Firma Przykładowa",
            outcome: "blocked",
            outcome_label: "Zablokowano",
            reason_code: "open_orders",
            reason: "Usunięcie zablokowane: Otwarte zamówienia (1).",
            actor_user_id: 1,
            actor_name: "Jan Testowy",
            actor_email: "jan@example.com",
            client_id: 7,
            client_name: "Firma Przykładowa",
            details: {},
          },
          {
            id: 1,
            occurred_at: "2026-09-10T08:30:00Z",
            event_type: "client.delete",
            event_label: "Usunięcie klienta",
            entity_type: "client",
            entity_type_label: "Klient",
            entity_id: 8,
            entity_label: "Firma Pusta",
            outcome: "executed",
            outcome_label: "Wykonano",
            reason_code: "purged",
            reason: "Klient pusty — usunięty trwale.",
            actor_user_id: 1,
            actor_name: "Jan Testowy",
            actor_email: "jan@example.com",
            client_id: 8,
            client_name: "Firma Pusta",
            details: {},
          },
        ],
      },
    });
    renderTab();

    expect(await screen.findByText("Firma Przykładowa")).toBeInTheDocument();
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Zablokowano")).toBeInTheDocument();
    expect(
      table.getByText("Usunięcie zablokowane: Otwarte zamówienia (1)."),
    ).toBeInTheDocument();
    expect(table.getByText("Firma Pusta")).toBeInTheDocument();
    expect(table.getByText("Wykonano")).toBeInTheDocument();
    expect(table.getAllByText("Jan Testowy")).toHaveLength(2);
    expect(mocks.get).toHaveBeenCalledWith("/api/settings/event-history", {
      params: expect.objectContaining({ limit: 50, offset: 0 }),
    });
  });

  it("brak uprawnień nie udaje pustej historii", async () => {
    mocks.get.mockRejectedValue(
      new AxiosError("Forbidden", "ERR_BAD_REQUEST", undefined, undefined, {
        status: 403,
        statusText: "Forbidden",
        headers: {},
        config: { headers: new AxiosHeaders() },
        data: { detail: "Requires one of roles" },
      }),
    );
    renderTab();

    expect(
      await screen.findByText("Historia zdarzeń jest dostępna dla ról Admin i Finanse."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Nie odnotowano jeszcze żadnych zdarzeń."),
    ).not.toBeInTheDocument();
  });
});
