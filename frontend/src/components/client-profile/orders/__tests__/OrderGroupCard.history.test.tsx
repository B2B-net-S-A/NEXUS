import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  OrderGroupCard,
  type OrderGroupFocusRequest,
} from "@/components/client-profile/orders/OrderGroupCard";
import type {
  OrderGroupRead,
  OrderHistoryEntry,
  OrderLineRead,
} from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: { events: vi.fn(), history: vi.fn() },
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
    md_optional_total: null,
    md_base_used: null,
    md_optional_used: null,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
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
    executive_contract: null,
    md_positions_total: null,
    md_used_total: null,
    contract_value_pln: null,
    used_value_pln: null,
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

function entry(overrides: Partial<OrderHistoryEntry> = {}): OrderHistoryEntry {
  return {
    key: "ev-1",
    category: "order",
    event_type: "utworzenie",
    type_label: "Utworzenie zamówienia",
    created_at: "2026-05-01T10:00:00Z",
    author_id: null,
    author_name: null,
    summary: "Zamówienie utworzone.",
    order_id: null,
    person_name: null,
    person_names: [],
    changes: [],
    balance_before: null,
    balance_after: null,
    details: [],
    import_id: null,
    import_period_month: null,
    import_people: null,
    import_md: null,
    related_group_id: null,
    related_order_number: null,
    ...overrides,
  };
}

function mockHistory(entries: OrderHistoryEntry[]) {
  const people = [...new Set(entries.flatMap((e) => e.person_names))].sort();
  vi.mocked(orderGroupsApi.history).mockResolvedValue({
    data: { entries, people },
  } as never);
}

const noop = () => {};

function renderCard(props: {
  group: OrderGroupRead;
  focusRequest?: OrderGroupFocusRequest | null;
  onFocusGroup?: (groupId: number) => void;
  clientId?: number;
  onEditLine?: (group: OrderGroupRead, line: OrderLineRead) => void;
  onSwapLine?: (group: OrderGroupRead, line: OrderLineRead) => void;
  onDeleteLine?: (group: OrderGroupRead, line: OrderLineRead) => void;
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree = (next: typeof props) => (
    <QueryClientProvider client={queryClient}>
      <OrderGroupCard
        clientId={next.clientId ?? 18}
        group={next.group}
        canManage
        canManageLifecycle
        onAddConsultant={noop}
        onEditGroup={noop}
        onEditLine={next.onEditLine ?? noop}
        onSwapLine={next.onSwapLine ?? noop}
        onDeleteLine={next.onDeleteLine ?? noop}
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

  it("każdy wpis nazywa wykonawcę: osobę, samo id po usunięciu konta albo system", async () => {
    // UAT B50: historia mówiła CO i KIEDY, ale nie KTO — nie dało się ustalić,
    // kto zmienił budżet. Pusty autor to zdarzenie automatyczne, nie brak danych.
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

    renderCard({ group: group() });
    await openHistory(user);

    const edited = (await screen.findByText("Edycja")).closest("li");
    expect(edited).toHaveTextContent("Anna Testowa");
    // Godzina obok daty — dwa wpisy tego samego dnia dało się dotąd tylko
    // uporządkować, nie umiejscowić w czasie.
    expect(edited).toHaveTextContent(/02\.05\.2026 \d{2}:\d{2}/);
    // Konto usunięte: identyfikator bez zgadywania nazwiska.
    expect(screen.getByText("Dodanie konsultanta").closest("li")).toHaveTextContent(
      "Użytkownik #9",
    );
    expect(screen.getByText("Zakończenie zamówienia").closest("li")).toHaveTextContent(
      "Automatycznie (system)",
    );
  });

  it("wpis transfer_md ma własną ikonę i klikalny numer zamówienia powiązanego", async () => {
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
          "Zamówienie zakończone — budżet MD wyczerpany, kontynuacja na zamówieniu nr 4500029903",
        related_group_id: 16,
        related_order_number: "4500029903",
      }),
    ]);
    const onFocusGroup = vi.fn();
    const user = userEvent.setup();

    renderCard({ group: group({ future_orders: [successor()] }), onFocusGroup });
    await openHistory(user);

    const transferRow = (await screen.findByText("Przeniesienie MD")).closest("li");
    expect(transferRow).not.toBeNull();
    // Przeniesienie MD to ruch MIĘDZY zamówieniami — ikona musi się różnić od
    // wpisu edycji, inaczej kolumna ikon nic nie rozróżnia.
    expect(transferRow!.querySelector(".lucide-arrow-left-right")).not.toBeNull();
    const editRow = screen.getByText("Edycja").closest("li");
    expect(editRow!.querySelector(".lucide-pencil")).not.toBeNull();
    expect(editRow!.querySelector(".lucide-arrow-left-right")).toBeNull();

    await user.click(
      screen.getByRole("button", { name: "Pokaż zamówienie nr 4500029903" }),
    );
    expect(onFocusGroup).toHaveBeenCalledWith(16);
  });

  it("wpis bez related_group_id renderuje sam tekst, bez martwego przycisku", async () => {
    mockHistory([
      entry({
        key: "ev-12",
        category: "consumption",
        event_type: "transfer_md",
        type_label: "Przeniesienie MD",
        summary:
          "Zamówienie zakończone — budżet MD wyczerpany, kontynuacja na zamówieniu nr 4500029904",
        related_group_id: null,
        related_order_number: "4500029904",
      }),
    ]);
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

  it("osoba dodana ręcznie i osoba z zakończoną współpracą mają swoją historię", async () => {
    const onKeepHistory = vi.fn();
    const onReplaceLine = vi.fn();
    const onDeleteLine = vi.fn();
    const ended = line({
      id: 7,
      consultant_name: "Marian Odeszły",
      status: "completed",
      is_active: false,
      start_date: "2026-03-30",
      end_date: "2026-08-12",
      cooperation_ended_on: "2026-08-12",
      invoiced_total: 25720,
      md_total: null,
      md_remaining: null,
      origin: "document",
    });
    const substitute = line({
      id: 8,
      consultant_name: "Tadeusz Zastępca",
      origin: "manual",
      added_by_name: "Anna Przykładowa",
      added_at: "2026-08-13T09:00:00Z",
      replaces_name: "Marian Odeszły",
      md_total: null,
      md_remaining: null,
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <OrderGroupCard
          clientId={15}
          group={group({
            is_cost_based: true,
            budget_amount: 40000,
            budget_used: 40000,
            budget_remaining: 0,
            has_file: true,
            lines: [ended, substitute],
          })}
          canManage
          canManageLifecycle
          onAddConsultant={noop}
          onEditGroup={noop}
          onEditLine={noop}
          onSwapLine={noop}
          onDeleteLine={onDeleteLine}
          onResolveOffboarding={noop}
          onKeepHistory={onKeepHistory}
          onReplaceLine={onReplaceLine}
          onDeleteGroup={noop}
          onCloseGroup={noop}
          onReopenGroup={noop}
          onExtendGroup={noop}
          onFocusGroup={noop}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByText("Dodany ręcznie")).toBeInTheDocument();
    expect(
      screen.getByText(/przez Anna Przykładowa jako zastępstwo za Marian Odeszły/),
    ).toBeInTheDocument();
    expect(screen.getByText(/PDF\) podpięto także do profilu tej osoby/)).toBeInTheDocument();
    expect(screen.getByText(/Zakończył współpracę 12\.08\.2026/)).toBeInTheDocument();
    // Ticket 09.2026: kto, ile i kiedy — wprost przy osobie, która odeszła.
    expect(
      screen.getByText(
        /Marian Odeszły wykorzystał\(a\) 25\s720,00\szł na tym zamówieniu przed zakończeniem współpracy — ta kwota nie wraca do puli/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/nie ma już aktywnej współpracy/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Zostaw jako historię" }));
    expect(onKeepHistory).toHaveBeenCalledWith(expect.anything(), ended);
    await user.click(screen.getByRole("button", { name: "Zastąp kimś innym" }));
    expect(onReplaceLine).toHaveBeenCalledWith(expect.anything(), ended);
    // Osoba ma zafakturowaną kwotę — usunięcie kasuje linię trwale, więc
    // serwer odmówiłby (409); przycisk jest wyłączony zawczasu.
    expect(screen.getByRole("button", { name: "Usuń z zamówienia" })).toBeDisabled();
    expect(onDeleteLine).not.toHaveBeenCalled();
  });
});

describe("OrderGroupCard — zakresy MD, następca i nagłówek CeZ", () => {
  const scopedGroup = () =>
    group({
      client_id: 115,
      executive_contract: {
        id: 71,
        number: "CeZ/242/2025",
        status: "active",
        framework_contract_id: 12,
        project_part: "cz2",
      },
      md_positions_total: 360,
      md_used_total: 154,
      contract_value_pln: 2_295_200,
      used_value_pln: 711_480,
      lines: [
        line({
          id: 1,
          consultant_name: "Tomasz Zastąpiony",
          status: "completed",
          is_active: false,
          cooperation_ended_on: "2026-06-30",
          md_total: 100,
          md_used: 100,
          md_optional_total: null,
          md_base_used: 100,
          replaced_by_order_id: 2,
          replaced_by_consultant_name: "Marcin Następca",
        }),
        line({
          id: 2,
          consultant_name: "Marcin Następca",
          md_total: 190,
          md_remaining: 206,
          md_used: 154,
          md_optional_total: 170,
          md_base_used: 154,
          md_optional_used: 0,
          predecessor_order_id: 1,
          predecessor_consultant_name: "Tomasz Zastąpiony",
        }),
      ],
    });

  it("osoba zastąpiona ma pill i przejście „→ następca”, które przewija do jego wiersza", async () => {
    const scrolled: Element[] = [];
    const scrollSpy = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(function (this: Element) {
        scrolled.push(this);
      });
    try {
      const user = userEvent.setup();
      renderCard({ group: scopedGroup() });

      expect(screen.getByText("Zastąpiony")).toBeInTheDocument();
      // Istniejąca linia „zastąpił:" u następcy zostaje.
      expect(screen.getByText("zastąpił: Tomasz Zastąpiony")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Pokaż następcę: Marcin Następca" }));
      expect(scrolled).toContain(document.getElementById("order-line-2"));
      expect(document.getElementById("order-line-2")).toHaveClass("ring-primary");
    } finally {
      scrollSpy.mockRestore();
    }
  });

  it("linia z zakresami dostaje dwa paski zużycia, a bez zakresów — stary pasek „pozostało”", () => {
    renderCard({ group: scopedGroup() });

    const successorRow = document.getElementById("order-line-2")!;
    expect(successorRow.querySelector('[aria-label="Podstawa — wykorzystano MD"]')).not.toBeNull();
    expect(successorRow.querySelector('[aria-label="Opcja — wykorzystano MD"]')).not.toBeNull();
    expect(successorRow).toHaveTextContent(/Wykorzystano łącznie 154 \/ 360 MD 43%/);

    // Zastąpiony: zakres podstawowy bez opcji — kursywa zamiast pustego paska.
    const replacedRow = document.getElementById("order-line-1")!;
    expect(replacedRow).toHaveTextContent("brak opcji w umowie");
  });

  it("Centrum e-Zdrowia: karta konsultanta z jawnym „pozostało” dla podstawy, opcji i łącznie", async () => {
    const user = userEvent.setup();
    const onEditLine = vi.fn();
    const onSwapLine = vi.fn();
    const onDeleteLine = vi.fn();
    renderCard({ group: scopedGroup(), clientId: 115, onEditLine, onSwapLine, onDeleteLine });

    const successorRow = document.getElementById("order-line-2")!;
    expect(successorRow).toHaveClass("rounded-xl", "bg-card");
    expect(successorRow.querySelector('[aria-label="Podstawa — wykorzystano MD"]')).not.toBeNull();
    expect(successorRow.querySelector('[aria-label="Opcja — wykorzystano MD"]')).not.toBeNull();
    expect(successorRow.querySelector('[aria-label="Łącznie — wykorzystano MD"]')).not.toBeNull();
    // 190 − 154 = 36 w podstawie, cała opcja 170, łącznie 206 (serwerowe md_remaining).
    expect(successorRow).toHaveTextContent(/Pozostało 36 MD/);
    expect(successorRow).toHaveTextContent(/Pozostało 170 MD/);
    expect(successorRow).toHaveTextContent(/154 \/ 360 MD \(43%\)/);
    expect(successorRow).toHaveTextContent(/pozostało 206 MD/);
    // Stary układ w tej karcie nie występuje.
    expect(successorRow).not.toHaveTextContent(/Wykorzystano łącznie/);

    // Bez opcji w umowie: komunikat zamiast paska, „Łącznie" liczy samą podstawę.
    const replacedRow = document.getElementById("order-line-1")!;
    expect(replacedRow).toHaveTextContent("Brak opcji w umowie");
    expect(replacedRow.querySelector('[aria-label="Opcja — wykorzystano MD"]')).toBeNull();
    expect(replacedRow).toHaveTextContent(/100 \/ 100 MD \(100%\)/);

    // Akcje przeniesione do nagłówka karty wołają te same handlery.
    await user.click(screen.getByRole("button", { name: "Edytuj linię — Marcin Następca" }));
    expect(onEditLine).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ id: 2 }));
    await user.click(screen.getByRole("button", { name: "Zamień kontraktora — Marcin Następca" }));
    expect(onSwapLine).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ id: 2 }));
    // Osoba ma zaraportowane MD — usunięcie kasuje linię trwale, więc kosz
    // jest wyłączony (serwer odpowiedziałby 409).
    expect(
      screen.getByRole("button", { name: "Usuń konsultanta z zamówienia — Marcin Następca" }),
    ).toBeDisabled();
    expect(onDeleteLine).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Zużycie MD — Marcin Następca" }),
    ).toBeInTheDocument();
  });

  it("ta sama karta z zakresami u innego klienta zostaje przy dotychczasowym wierszu", () => {
    renderCard({ group: scopedGroup(), clientId: 18 });
    const successorRow = document.getElementById("order-line-2")!;
    expect(successorRow).not.toHaveClass("rounded-xl");
    expect(successorRow).toHaveTextContent(/Wykorzystano łącznie 154 \/ 360 MD 43%/);
    expect(successorRow.querySelector('[aria-label="Łącznie — wykorzystano MD"]')).toBeNull();
    expect(successorRow).not.toHaveTextContent(/Pozostało/);
  });

  it("BIK/Polkomtel bez zakresów nie zmienia się wizualnie", () => {
    renderCard({ group: group() });
    expect(screen.getByRole("progressbar", { name: "Pozostałe MD" })).toBeInTheDocument();
    expect(screen.queryByText(/Wykorzystano łącznie/)).toBeNull();
    expect(screen.queryByText(/Umowa wykonawcza/)).toBeNull();
    expect(screen.queryByRole("progressbar", { name: "Wykorzystane MD zamówienia" })).toBeNull();
  });

  it("BIK/Polkomtel z serwerowym podziałem i sumami pozycji NADAL ma stary pasek i żadnego nagłówka CeZ", () => {
    // Przegląd adwersarialny 09.2026: backend zwraca `md_base_used` dla każdej
    // linii z `md_total` i `md_positions_total` dla każdego zamówienia MD per
    // osoba — nie tylko u CeZ. Bramką jest umowa wykonawcza na karcie.
    renderCard({
      group: group({
        executive_contract: null,
        md_positions_total: 50,
        md_used_total: 50,
        contract_value_pln: 60_000,
        used_value_pln: 60_000,
        lines: [line({ md_used: 50, md_base_used: 50, md_optional_used: null })],
      }),
    });
    expect(screen.getByRole("progressbar", { name: "Pozostałe MD" })).toBeInTheDocument();
    expect(screen.queryByRole("progressbar", { name: /Podstawa/ })).toBeNull();
    expect(screen.queryByText(/Wykorzystano łącznie/)).toBeNull();
    expect(screen.queryByText(/brak opcji w umowie/)).toBeNull();
    expect(screen.queryByRole("progressbar", { name: "Wykorzystane MD zamówienia" })).toBeNull();
    expect(screen.queryByText(/Wykorzystano wartości umowy/)).toBeNull();
    expect(screen.queryByText(/60\s000/)).toBeNull();
  });

  it("osoba już zastąpiona nie dostaje pytania „Zastąp kimś innym” — decyzja już zapadła", () => {
    renderCard({ group: scopedGroup() });
    const replacedRow = document.getElementById("order-line-1")!;
    expect(replacedRow).toHaveTextContent("Zastąpiony");
    expect(screen.queryByRole("button", { name: "Zastąp kimś innym" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Zostaw jako historię" })).toBeNull();
    expect(screen.queryByText(/nie ma już aktywnej współpracy/)).toBeNull();
  });

  it("nagłówek: umowa wykonawcza z częścią, pasek pozycji MD i wartość umowy dla ról z finansami", () => {
    renderCard({ group: scopedGroup() });

    expect(screen.getByText("Umowa wykonawcza CeZ/242/2025 · Cz. II")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "Wykorzystane MD zamówienia" });
    expect(bar).toHaveAttribute("aria-valuenow", "43");
    expect(bar.parentElement).toHaveTextContent(/Wykorzystano 154 \/ 360 MD \(43%\)/);
    // 711 480 / 2 295 200 = 31%
    expect(bar.parentElement).toHaveTextContent(/Wykorzystano wartości umowy 31%/);
    expect(bar.parentElement).toHaveTextContent(/711\s480,00\szł \/ 2\s295\s200,00\szł/);
  });

  it("rola bez finansów widzi w nagłówku same MD — bez „0 zł z 0 zł”", () => {
    renderCard({
      group: { ...scopedGroup(), contract_value_pln: null, used_value_pln: null },
    });
    expect(screen.getByRole("progressbar", { name: "Wykorzystane MD zamówienia" })).toBeInTheDocument();
    expect(screen.queryByText(/Wykorzystano wartości umowy/)).toBeNull();
    expect(screen.queryByText(/2\s295\s200/)).toBeNull();
  });

  it("wiersz MD per osoba ma przycisk rozliczeń miesięcznych; kosztowe i wspólna pula — nie", () => {
    renderCard({ group: scopedGroup() });
    expect(
      screen.getByRole("button", { name: "Zużycie MD — Marcin Następca" }),
    ).toBeInTheDocument();
  });
});

describe("OrderGroupCard — kto stoi w „Zakończonych\u201d", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(orderGroupsApi.history).mockResolvedValue({
      data: { entries: [], people: [] },
    } as never);
  });

  /** Osoba po zejściu ma DALEJ `status: "active"` — linia MD kończy się
   *  budżetem, nie kalendarzem. Do sekcji decyduje `is_active` z serwera. */
  const departed = (overrides: Partial<OrderLineRead> = {}) =>
    line({
      status: "active",
      is_active: false,
      md_total: 50,
      md_remaining: 20,
      md_used: 30,
      ...overrides,
    });

  it("zakończeni schodzą z aktywnej obsady, najnowsze zejście na górze", () => {
    renderCard({
      group: group({
        active_consultants: 1,
        lines: [
          line({ id: 1, consultant_name: "Aktywna Osoba", md_remaining: 20 }),
          departed({
            id: 2,
            consultant_name: "Anna Wczesna",
            end_date: "2026-06-30",
            cooperation_ended_on: "2026-06-30",
          }),
          departed({
            id: 3,
            consultant_name: "Zenon Ostatni",
            end_date: "2026-08-31",
            cooperation_ended_on: "2026-08-31",
          }),
        ],
      }),
    });

    const active = screen.getByRole("region", { name: "Aktywna obsada" });
    const ended = screen.getByRole("region", { name: "Zakończone" });
    expect(active).toHaveTextContent("Aktywna Osoba");
    expect(active).not.toHaveTextContent("Zenon Ostatni");

    const order = Array.from(ended.querySelectorAll("li")).map(
      (item) => item.textContent ?? "",
    );
    expect(order).toHaveLength(2);
    // Alfabetycznie byłoby odwrotnie — sekcja sortuje się datą zejścia.
    expect(order[0]).toContain("Zenon Ostatni");
    expect(order[1]).toContain("Anna Wczesna");
  });

  it("wiersz w „Zakończonych” niesie okres, zużycie i datę zejścia", () => {
    renderCard({
      group: group({
        active_consultants: 0,
        lines: [
          departed({
            id: 2,
            consultant_name: "Marian Odeszły",
            start_date: "2026-05-01",
            end_date: "2026-08-31",
            cooperation_ended_on: "2026-08-31",
          }),
        ],
      }),
    });

    const ended = screen.getByRole("region", { name: "Zakończone" });
    expect(ended).toHaveTextContent(/Zakończył współpracę 31\.08\.2026/);
    expect(ended).toHaveTextContent(/był na zamówieniu od 01\.05\.2026 do 31\.08\.2026/);
    expect(ended).toHaveTextContent(
      /Marian Odeszły wykorzystał\(a\).*na tym zamówieniu przed zakończeniem współpracy/,
    );
  });

  it("zamiana kontraktora zostaje dostępna, dopóki linia jest aktywna w bazie", () => {
    renderCard({
      group: group({
        active_consultants: 0,
        lines: [
          departed({ id: 2, consultant_name: "Marian Odeszły", end_date: "2026-08-31" }),
          line({
            id: 3,
            consultant_name: "Domknięta Linia",
            status: "completed",
            is_active: false,
            md_remaining: 0,
          }),
        ],
      }),
    });

    // Serwer (`swap_consultant`) pyta o status linii, nie o obsadę — bramka
    // po `is_active` blokowałaby zamianę, na którą serwer pozwala.
    expect(
      screen.getByRole("button", { name: "Zamień kontraktora — Marian Odeszły" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Zamień kontraktora — Domknięta Linia" }),
    ).toBeDisabled();
  });
});

describe("OrderGroupCard — usuwanie konsultanta z zamówienia", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("linia bez rozliczeń: kosz aktywny i woła onDeleteLine", async () => {
    const user = userEvent.setup();
    const onDeleteLine = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const g = group({ lines: [line({ md_used: 0 })] });
    render(
      <QueryClientProvider client={queryClient}>
        <OrderGroupCard
          clientId={18}
          group={g}
          canManage
          canManageLifecycle
          onAddConsultant={noop}
          onEditGroup={noop}
          onEditLine={noop}
          onSwapLine={noop}
          onDeleteLine={onDeleteLine}
          onResolveOffboarding={noop}
          onDeleteGroup={noop}
          onCloseGroup={noop}
          onReopenGroup={noop}
          onExtendGroup={noop}
          onFocusGroup={noop}
          focusRequest={null}
        />
      </QueryClientProvider>,
    );
    const button = screen.getByRole("button", {
      name: /Usuń konsultanta z zamówienia — Michał Leśniak/,
    });
    expect(button).toBeEnabled();
    await user.click(button);
    expect(onDeleteLine).toHaveBeenCalledWith(g, g.lines[0]);
  });

  it("linia z zaraportowanymi MD: kosz wyłączony z wyjaśnieniem", () => {
    renderCard({ group: group({ lines: [line({ md_used: 12 })] }) });
    const button = screen.getByRole("button", {
      name: /Usuń konsultanta z zamówienia — Michał Leśniak/,
    });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute(
      "title",
      expect.stringContaining("ma rozliczenia"),
    );
  });
});
