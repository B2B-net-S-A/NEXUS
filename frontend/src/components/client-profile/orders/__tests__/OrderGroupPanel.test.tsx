/**
 * Panel zamówienia MD/kosztowego (wersja B, 29.09.2026) — historia, nagłówek
 * umowy wykonawczej, przyszłe zamówienia i akcje cyklu życia, których dawniej
 * pilnowały testy karty `OrderGroupCard`.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { OrderGroupPanel } from "@/components/client-profile/orders/OrderGroupPanel";
import type { OrderGroupRead, OrderHistoryEntry } from "@/lib/api/orderGroups";
import {
  makeHistoryEntry as entry,
  makeOrderGroup as group,
  makeOrderLine as line,
} from "@/test/fixtures/order-groups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: { history: vi.fn() },
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

function mockHistory(entries: OrderHistoryEntry[]) {
  const people = [...new Set(entries.flatMap((item) => item.person_names))].sort();
  vi.mocked(orderGroupsApi.history).mockResolvedValue({
    data: { entries, people },
  } as never);
}

function successor(): OrderGroupRead {
  return group({
    id: 16,
    order_number: "4599029903",
    start_date: "2026-08-15",
    status: "scheduled",
    status_label: "Zaplanowane",
    lines: [
      line({
        id: 9,
        group_id: 16,
        contract_id: 800,
        consultant_name: "Przyszły Konsultant",
        status: "draft",
        md_total: 22,
        md_remaining: 22,
      }),
    ],
    active_consultants: 0,
    event_count: 1,
  });
}

function actions() {
  return {
    onAddConsultant: vi.fn(),
    onEditGroup: vi.fn(),
    onEditLine: vi.fn(),
    onExtendGroup: vi.fn(),
    onCloseGroup: vi.fn(),
    onReopenGroup: vi.fn(),
    onCancelGroup: vi.fn(),
    onRestoreGroup: vi.fn(),
    onDeleteGroup: vi.fn(),
    onClose: vi.fn(),
    onSelectLine: vi.fn(),
    onSelectGroup: vi.fn(),
  };
}

function renderPanel(
  value: OrderGroupRead,
  options: {
    parent?: OrderGroupRead | null;
    canManage?: boolean;
    canManageLifecycle?: boolean;
    clientId?: number;
  } = {},
) {
  const handlers = actions();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <OrderGroupPanel
          clientId={options.clientId ?? 18}
          group={value}
          parent={options.parent ?? null}
          canManage={options.canManage ?? true}
          canManageLifecycle={options.canManageLifecycle ?? true}
          searchQuery=""
          {...handlers}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return handlers;
}

async function openHistory(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("tab", { name: /^Historia/ }));
}

describe("OrderGroupPanel — historia zamówienia", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("każdy wpis nazywa wykonawcę: osobę, samo id po usunięciu konta albo system", async () => {
    // UAT B50: historia mówiła CO i KIEDY, ale nie KTO.
    mockHistory([
      entry({
        key: "edit-20",
        category: "edits",
        event_type: "edycja_reczna",
        type_label: "Edycja",
        summary: "budżet MD: 50 MD → 60 MD.",
        changes: [{ label: "budżet MD", before: "50 MD", after: "60 MD" }],
        author_id: 5,
        author_name: "Anna Testowa",
        created_at: "2026-05-02T09:15:00Z",
      }),
      entry({
        key: "ev-21",
        category: "consultants",
        event_type: "dodanie_konsultanta",
        type_label: "Dodanie konsultanta",
        summary: "Dodano osobę.",
        author_id: 9,
        author_name: null,
      }),
      entry({
        key: "ev-22",
        event_type: "zakonczenie",
        type_label: "Zakończenie zamówienia",
        summary: "Zamówienie zakończone — budżet MD wyczerpany.",
      }),
    ]);
    const user = userEvent.setup();

    renderPanel(group());
    expect(screen.getByRole("tab", { name: "Historia (2)" })).toBeInTheDocument();
    await openHistory(user);

    const edited = (await screen.findByText("Edycja")).closest("li");
    expect(edited).toHaveTextContent("Anna Testowa");
    expect(edited).toHaveTextContent(/02\.05\.2026 \d{2}:\d{2}/);
    expect(screen.getByText("Dodanie konsultanta").closest("li")).toHaveTextContent(
      "Użytkownik #9",
    );
    expect(screen.getByText("Zakończenie zamówienia").closest("li")).toHaveTextContent(
      "Automatycznie (system)",
    );
    expect(orderGroupsApi.history).toHaveBeenCalledWith(18, 15);
  });

  it("wpis transfer_md ma własną ikonę i numer, który otwiera panel zamówienia powiązanego", async () => {
    mockHistory([
      entry({
        key: "edit-10",
        category: "edits",
        event_type: "edycja_reczna",
        type_label: "Edycja",
        summary: "Zmieniono: budżet MD.",
        changes: [{ label: "budżet MD", before: null, after: null }],
      }),
      entry({
        key: "ev-11",
        category: "consumption",
        event_type: "transfer_md",
        type_label: "Przeniesienie MD",
        summary:
          "Zamówienie zakończone — budżet MD wyczerpany, kontynuacja na zamówieniu nr 4599029903",
        related_group_id: 16,
        related_order_number: "4599029903",
      }),
    ]);
    const user = userEvent.setup();

    const handlers = renderPanel(group({ future_orders: [successor()] }));
    await openHistory(user);

    const transferRow = (await screen.findByText("Przeniesienie MD")).closest("li");
    expect(transferRow!.querySelector(".lucide-arrow-left-right")).not.toBeNull();
    const editRow = screen.getByText("Edycja").closest("li");
    expect(editRow!.querySelector(".lucide-pencil")).not.toBeNull();
    expect(editRow!.querySelector(".lucide-arrow-left-right")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Pokaż zamówienie nr 4599029903" }));
    // W tabeli z panelem „pokaż zamówienie" = zaznacz jego wiersz i otwórz panel.
    expect(handlers.onSelectGroup).toHaveBeenCalledWith(16);
  });

  it("wpis bez related_group_id renderuje sam tekst, bez martwego przycisku", async () => {
    mockHistory([
      entry({
        key: "ev-12",
        category: "consumption",
        event_type: "transfer_md",
        type_label: "Przeniesienie MD",
        summary:
          "Zamówienie zakończone — budżet MD wyczerpany, kontynuacja na zamówieniu nr 4599029904",
        related_group_id: null,
        related_order_number: "4599029904",
      }),
    ]);
    const user = userEvent.setup();

    renderPanel(group());
    await openHistory(user);

    expect(await screen.findByText(/kontynuacja na zamówieniu nr 4599029904/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pokaż zamówienie nr/ })).toBeNull();
  });
});

describe("OrderGroupPanel — nagłówek umowy wykonawczej", () => {
  const scoped = () =>
    group({
      client_id: 115,
      executive_contract: {
        id: 71,
        number: "UW/242/2031",
        status: "active",
        framework_contract_id: 12,
        project_part: "cz2",
      },
      md_positions_total: 360,
      md_used_total: 154,
      contract_value_pln: 2_295_200,
      used_value_pln: 711_480,
    });

  it("umowa wykonawcza z częścią, pasek pozycji MD i wartość umowy dla ról z finansami", () => {
    renderPanel(scoped(), { clientId: 115 });

    expect(screen.getByText("Umowa wykonawcza UW/242/2031 · Cz. II")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "Wykorzystane MD zamówienia" });
    expect(bar).toHaveAttribute("aria-valuenow", "43");
    expect(bar.parentElement).toHaveTextContent(/Wykorzystano 154 \/ 360 MD \(43%\)/);
    // 711 480 / 2 295 200 = 31%
    expect(bar.parentElement).toHaveTextContent(/Wykorzystano wartości umowy 31%/);
    expect(bar.parentElement).toHaveTextContent(/711\s480,00\szł \/ 2\s295\s200,00\szł/);
  });

  it("rola bez finansów widzi same MD — bez „0 zł z 0 zł”", () => {
    renderPanel({ ...scoped(), contract_value_pln: null, used_value_pln: null }, { clientId: 115 });
    expect(screen.getByRole("progressbar", { name: "Wykorzystane MD zamówienia" })).toBeInTheDocument();
    expect(screen.queryByText(/Wykorzystano wartości umowy/)).toBeNull();
    expect(screen.queryByText(/2\s295\s200/)).toBeNull();
  });

  it("BIK/Polkomtel z serwerowymi sumami pozycji NIE dostaje nagłówka umowy wykonawczej", () => {
    // Backend zwraca `md_positions_total` dla każdego zamówienia MD per osoba —
    // bramką jest umowa wykonawcza na zamówieniu.
    renderPanel(
      group({
        md_positions_total: 50,
        md_used_total: 50,
        contract_value_pln: 60_000,
        used_value_pln: 60_000,
      }),
    );
    expect(screen.queryByText(/Umowa wykonawcza/)).toBeNull();
    expect(screen.queryByRole("progressbar", { name: "Wykorzystane MD zamówienia" })).toBeNull();
    expect(screen.queryByText(/Wykorzystano wartości umowy/)).toBeNull();
  });
});

describe("OrderGroupPanel — budżet kosztowy", () => {
  it("trzy liczby i pasek pozostałości", () => {
    renderPanel(
      group({
        is_cost_based: true,
        budget_amount: 50000,
        budget_used: 30000,
        budget_remaining: 20000,
        lines: [line({ md_total: null, md_remaining: null })],
      }),
    );
    const budget = screen.getByText(/^Kwota/);
    expect(budget).toHaveTextContent(/Kwota 50\s000,00\szł · wykorzystano 30\s000,00\szł · pozostało 20\s000,00\szł/);
    expect(screen.getByRole("progressbar", { name: "Pozostała kwota zamówienia" })).toHaveAttribute(
      "aria-valuenow",
      "40",
    );
  });

  it("brak uprawnień do kwot NIE czyta się jak wyczerpany budżet", () => {
    renderPanel(
      group({
        is_cost_based: true,
        budget_amount: null,
        budget_used: null,
        budget_remaining: null,
        lines: [line({ md_total: null, md_remaining: null })],
      }),
    );
    expect(screen.getByText(/^Kwota/)).toHaveTextContent("Kwota — · wykorzystano — · pozostało —");
    expect(screen.queryByRole("progressbar", { name: "Pozostała kwota zamówienia" })).toBeNull();
    expect(screen.queryByText(/Budżet wyczerpany/)).toBeNull();
  });
});

describe("OrderGroupPanel — obsada i przyszłe zamówienia", () => {
  it("lista konsultantów otwiera panel osoby, a puste zamówienie mówi to wprost", async () => {
    const user = userEvent.setup();
    const handlers = renderPanel(
      group({
        lines: [
          line({ id: 1, consultant_name: "Michał Przykładowy" }),
          line({
            id: 2,
            consultant_name: "Anna Zejście",
            status: "completed",
            is_active: false,
            history_kept_at: "2026-08-01T09:00:00Z",
          }),
        ],
      }),
    );
    expect(screen.getByText("1 osoba · 1 zakończone")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Anna Zejście/ }));
    expect(handlers.onSelectLine).toHaveBeenCalledWith(15, 2);
  });

  it("zamówienie bez konsultantów pokazuje pusty stan zamiast znikającej sekcji", () => {
    renderPanel(group({ lines: [], active_consultants: 0 }));
    expect(screen.getByText("Konsultanci (0)")).toBeInTheDocument();
    expect(screen.getByText("To zamówienie nie ma jeszcze konsultantów.")).toBeInTheDocument();
  });

  it("przyszłe zamówienie: nazwisko prowadzi do kontraktu, akcje wołają te same okna", async () => {
    const user = userEvent.setup();
    const future = successor();
    const handlers = renderPanel(group({ future_orders: [future] }));

    expect(screen.getByText("Przyszłe zamówienia (1)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Przyszły Konsultant" })).toHaveAttribute(
      "href",
      "/contracts/800",
    );
    await user.click(
      screen.getByRole("button", { name: "Uzupełnij przyszłe zamówienie nr 4599029903" }),
    );
    expect(handlers.onEditGroup).toHaveBeenCalledWith(future);
    await user.click(
      screen.getByRole("button", {
        name: "Dodaj konsultanta do przyszłego zamówienia nr 4599029903",
      }),
    );
    expect(handlers.onAddConsultant).toHaveBeenCalledWith(future);
    await user.click(
      screen.getByRole("button", { name: "Usuń przyszłe zamówienie nr 4599029903" }),
    );
    expect(handlers.onDeleteGroup).toHaveBeenCalledWith(future);
  });

  it("panel przedłużenia prowadzi do zamówienia, które przedłuża", async () => {
    const user = userEvent.setup();
    const parent = group({ future_orders: [successor()] });
    const handlers = renderPanel(successor(), { parent });
    expect(screen.getByText(/Przedłużenie zamówienia/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "4599030067" }));
    expect(handlers.onSelectGroup).toHaveBeenCalledWith(15);
  });
});

describe("OrderGroupPanel — akcje cyklu życia", () => {
  async function openMenu(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: "Więcej akcji zamówienia" }));
    return screen.findByRole("menu");
  }

  it("aktywne: Zakończ, Anuluj i Usuń; każda akcja woła swoje okno", async () => {
    const user = userEvent.setup();
    const value = group();
    const handlers = renderPanel(value);

    let menu = await openMenu(user);
    expect(within(menu).getByRole("menuitem", { name: /^Zakończ$/ })).toBeInTheDocument();
    expect(within(menu).queryByRole("menuitem", { name: /^Przywróć$/ })).toBeNull();
    expect(within(menu).queryByRole("menuitem", { name: /Przywróć anulowane/ })).toBeNull();
    await user.click(within(menu).getByRole("menuitem", { name: /^Zakończ$/ }));
    await waitFor(() => expect(handlers.onCloseGroup).toHaveBeenCalledWith(value));

    menu = await openMenu(user);
    await user.click(within(menu).getByRole("menuitem", { name: /Anuluj zamówienie/ }));
    await waitFor(() => expect(handlers.onCancelGroup).toHaveBeenCalledWith(value));

    menu = await openMenu(user);
    await user.click(within(menu).getByRole("menuitem", { name: /Usuń całe zamówienie/ }));
    await waitFor(() => expect(handlers.onDeleteGroup).toHaveBeenCalledWith(value));

    await user.click(screen.getByRole("button", { name: "Dodaj przedłużenie" }));
    expect(handlers.onExtendGroup).toHaveBeenCalledWith(value);
    await user.click(screen.getByRole("button", { name: "Uzupełnij zamówienie" }));
    expect(handlers.onEditGroup).toHaveBeenCalledWith(value);
  });

  it("zakończone: tylko „Przywróć”, bez „Zakończ”", async () => {
    const user = userEvent.setup();
    const value = group({ status: "completed", status_label: "Zakończone", closure_date: "2026-06-30" });
    const handlers = renderPanel(value);
    expect(screen.getByText("Zakończone", { selector: "dt" }).nextElementSibling).toHaveTextContent(
      "30.06.2026",
    );

    const menu = await openMenu(user);
    expect(within(menu).queryByRole("menuitem", { name: /^Zakończ$/ })).toBeNull();
    await user.click(within(menu).getByRole("menuitem", { name: /^Przywróć$/ }));
    await waitFor(() => expect(handlers.onReopenGroup).toHaveBeenCalledWith(value));
  });

  it("anulowane: „Przywróć anulowane”, bez edycji i przedłużenia, z datą anulowania w kalendarzu firmy", async () => {
    const user = userEvent.setup();
    const value = group({
      status: "cancelled",
      status_label: "Anulowane",
      cancelled_at: "2026-09-28T23:30:00Z",
      cancellation_reason: "klient wycofał zapytanie",
    });
    const handlers = renderPanel(value);

    expect(screen.getByText("29.09.2026 — klient wycofał zapytanie")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Uzupełnij zamówienie" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dodaj przedłużenie" })).toBeNull();
    const menu = await openMenu(user);
    expect(within(menu).queryByRole("menuitem", { name: /Anuluj zamówienie/ })).toBeNull();
    await user.click(within(menu).getByRole("menuitem", { name: /Przywróć anulowane/ }));
    await waitFor(() => expect(handlers.onRestoreGroup).toHaveBeenCalledWith(value));
  });

  it("wyczerpane: dodanie konsultanta zablokowane z powodem", () => {
    renderPanel(
      group({
        status: "exhausted",
        status_label: "Wyczerpane",
        can_add_consultant: false,
        is_cost_based: true,
        budget_amount: 1000,
        budget_used: 1000,
        budget_remaining: 0,
      }),
    );
    const add = screen.getByRole("button", { name: "Dodaj konsultanta" });
    expect(add).toBeDisabled();
    expect(add).toHaveAttribute("title", "Zamówienie jest wyczerpane — nie można dodać konsultanta");
    expect(screen.getByRole("status")).toHaveTextContent(/Budżet wyczerpany/);
  });

  it("bez roli cyklu życia nie ma menu ani przedłużenia; bez obsady — dodawania", () => {
    renderPanel(group(), { canManage: false, canManageLifecycle: false });
    expect(screen.queryByRole("button", { name: "Więcej akcji zamówienia" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dodaj przedłużenie" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dodaj konsultanta" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Uzupełnij zamówienie" })).toBeNull();
  });
});
