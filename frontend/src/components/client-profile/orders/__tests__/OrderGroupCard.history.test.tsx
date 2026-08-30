import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  OrderGroupCard,
  type OrderGroupFocusRequest,
} from "@/components/client-profile/orders/OrderGroupCard";
import type {
  OrderGroupEvent,
  OrderGroupRead,
  OrderLineRead,
} from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: { events: vi.fn() },
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

function line(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 1,
    group_id: 15,
    contract_id: 100,
    candidate_id: 5,
    consultant_name: "Michał Leśniak",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2026-05-01",
    end_date: null,
    rate_cost: 1000,
    rate_revenue: 1200,
    input_value: 50,
    input_mode: "md",
    md_total: 50,
    md_remaining: 0,
    md_manual_adjustment: 0,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    ...overrides,
  };
}

function group(overrides: Partial<OrderGroupRead> = {}): OrderGroupRead {
  return {
    id: 15,
    client_id: 18,
    order_number: "4500030067",
    start_date: "2026-05-01",
    end_date: null,
    notes: null,
    created_at: "2026-05-01T10:00:00Z",
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
    lines: [line()],
    active_consultants: 1,
    event_count: 2,
    future_orders: [],
    ...overrides,
  };
}

function successor(): OrderGroupRead {
  return group({
    id: 16,
    order_number: "4500029903",
    start_date: "2026-08-15",
    status: "scheduled",
    status_label: "Zaplanowane",
    lines: [line({ id: 2, group_id: 16, status: "draft", md_total: 22, md_remaining: 22 })],
    active_consultants: 0,
    event_count: 1,
  });
}

function event(overrides: Partial<OrderGroupEvent> = {}): OrderGroupEvent {
  return {
    id: 1,
    event_type: "utworzenie",
    event_label: "Utworzenie",
    description: "Zamówienie utworzone.",
    order_id: null,
    payload: null,
    related_group_id: null,
    related_order_number: null,
    created_by_user_id: null,
    created_at: "2026-05-01T10:00:00Z",
    ...overrides,
  };
}

const noop = () => {};

function renderCard(props: {
  group: OrderGroupRead;
  focusRequest?: OrderGroupFocusRequest | null;
  onFocusGroup?: (groupId: number) => void;
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree = (next: typeof props) => (
    <QueryClientProvider client={queryClient}>
      <OrderGroupCard
        clientId={18}
        group={next.group}
        canManage
        canManageLifecycle
        onAddConsultant={noop}
        onEditGroup={noop}
        onEditLine={noop}
        onSwapLine={noop}
        onDeleteLine={noop}
        onResolveOffboarding={noop}
        onDeleteGroup={noop}
        onCloseGroup={noop}
        onReopenGroup={noop}
        onExtendGroup={noop}
        onFocusGroup={next.onFocusGroup ?? noop}
        focusRequest={next.focusRequest ?? null}
      />
    </QueryClientProvider>
  );
  const view = render(tree(props));
  return {
    ...view,
    update: (next: Partial<typeof props>) =>
      view.rerender(tree({ ...props, ...next })),
  };
}

async function openHistory(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /Historia zamówienia/ }));
}

describe("OrderGroupCard — historia zamówienia", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("wpis transfer_md ma własną ikonę i klikalny numer zamówienia powiązanego", async () => {
    vi.mocked(orderGroupsApi.events).mockResolvedValue({
      data: {
        events: [
          event({
            id: 10,
            event_type: "edycja_reczna",
            event_label: "Edycja ręczna",
            description: "Zmieniono: budżet MD.",
          }),
          event({
            id: 11,
            event_type: "transfer_md",
            event_label: "Przeniesienie MD",
            description:
              "Zamówienie zakończone — budżet MD wyczerpany, kontynuacja na zamówieniu nr 4500029903",
            related_group_id: 16,
            related_order_number: "4500029903",
          }),
        ],
      },
    } as never);
    const onFocusGroup = vi.fn();
    const user = userEvent.setup();

    renderCard({ group: group({ future_orders: [successor()] }), onFocusGroup });
    await openHistory(user);

    const transferRow = (await screen.findByText("Przeniesienie MD")).closest("li");
    expect(transferRow).not.toBeNull();
    // Przeniesienie MD to ruch MIĘDZY zamówieniami — ikona musi się różnić od
    // wpisu edycji, inaczej kolumna ikon nic nie rozróżnia.
    expect(transferRow!.querySelector(".lucide-arrow-left-right")).not.toBeNull();
    const editRow = screen.getByText("Edycja ręczna").closest("li");
    expect(editRow!.querySelector(".lucide-pencil")).not.toBeNull();
    expect(editRow!.querySelector(".lucide-arrow-left-right")).toBeNull();

    await user.click(
      screen.getByRole("button", { name: "Pokaż zamówienie nr 4500029903" }),
    );
    expect(onFocusGroup).toHaveBeenCalledWith(16);
  });

  it("wpis bez related_group_id renderuje sam tekst, bez martwego przycisku", async () => {
    vi.mocked(orderGroupsApi.events).mockResolvedValue({
      data: {
        events: [
          event({
            id: 12,
            event_type: "transfer_md",
            event_label: "Przeniesienie MD",
            description:
              "Zamówienie zakończone — budżet MD wyczerpany, kontynuacja na zamówieniu nr 4500029904",
            related_group_id: null,
            related_order_number: "4500029904",
          }),
        ],
      },
    } as never);
    const user = userEvent.setup();

    renderCard({ group: group() });
    await openHistory(user);

    expect(
      await screen.findByText(/kontynuacja na zamówieniu nr 4500029904/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Pokaż zamówienie nr/ }),
    ).not.toBeInTheDocument();
  });

  it("żądanie pokazania rozwija zwiniętą kartę i przewija do zagnieżdżonego zamówienia", async () => {
    const scrolled: Element[] = [];
    // `scrollIntoView` na PROTOTYPIE to stan globalny środowiska, a `setup.ts`
    // instaluje tam no-op, bez którego cmdk (Popover/Command w filtrach) nie
    // montuje się w jsdom. Szpieg zostawiony bez przywrócenia wycieka poza ten
    // plik i wywraca cudze testy — objaw jest mylący, bo pada nie ta sekcja,
    // która coś popsuła. Restore jest w `finally`, żeby nieudana asercja też
    // go oddała.
    const scrollSpy = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(function (this: Element) {
        scrolled.push(this);
      });
    try {
      const user = userEvent.setup();
      const parent = group({ future_orders: [successor()] });

      const { update } = renderCard({ group: parent, focusRequest: null });
      await user.click(
        screen.getByRole("button", { name: "Zwiń zamówienie nr 4500030067" }),
      );
      // Zagnieżdżone zamówienie NIE istnieje w DOM zwiniętej karty — samo
      // `scrollIntoView` nie miałoby do czego trafić.
      expect(screen.queryByText(/nr 4500029903/)).not.toBeInTheDocument();

      update({ focusRequest: { groupId: 16, nonce: 1 } });

      expect(screen.getByText(/nr 4500029903/)).toBeInTheDocument();
      expect(scrolled).toContain(
        document.getElementById("order-group-anchor-16"),
      );
    } finally {
      scrollSpy.mockRestore();
    }
  });
});
