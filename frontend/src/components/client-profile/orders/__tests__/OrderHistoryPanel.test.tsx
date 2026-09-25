import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrderHistoryPanel } from "@/components/client-profile/orders/OrderHistoryPanel";
import type { OrderHistoryEntry } from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: { history: vi.fn() },
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

function entry(overrides: Partial<OrderHistoryEntry>): OrderHistoryEntry {
  return {
    key: "k",
    category: "order",
    event_type: "utworzenie",
    type_label: "Utworzenie zamówienia",
    created_at: "2026-08-21T09:31:00Z",
    author_id: 7,
    author_name: "Anna Korycka",
    summary: "Utworzono zamówienie nr 4500030197",
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

const TEPER_SERIES = entry({
  key: "edit-522",
  category: "edits",
  event_type: "edycja_reczna",
  type_label: "Edycja",
  created_at: "2026-09-24T12:25:01Z",
  summary: "6 zmian w serii edycji",
  order_id: 146,
  person_name: "Konrad Teper",
  person_names: ["Konrad Teper"],
  changes: [
    { label: "stawka kosztowa", before: "560 zł/MD", after: "580 zł/MD" },
    { label: "budżet MD", before: "9,66 MD", after: "10 MD" },
  ],
  balance_before: -4,
  balance_after: 5.963,
  details: Array.from({ length: 6 }, (_, i) => ({
    created_at: `2026-09-24T12:2${i}:00Z`,
    author_id: 7,
    author_name: "Anna Korycka",
    text: `Zmiana nr ${i + 1}`,
  })),
});

const IMPORT = entry({
  key: "import-import_md-2",
  category: "consumption",
  event_type: "import_md",
  type_label: "Import MD",
  created_at: "2026-09-23T11:40:03Z",
  summary: "Import MD za sierpień 2026 – 2 osoby, 25 MD",
  person_names: ["Paweł Łaski", "Konrad Teper"],
  import_id: 2,
  import_period_month: "2026-08",
  import_people: 2,
  import_md: 25,
});

const NEGATIVE = entry({
  key: "edit-9",
  category: "edits",
  event_type: "edycja_reczna",
  type_label: "Edycja",
  created_at: "2026-09-22T10:00:00Z",
  summary: "ręczna korekta MD: 0 MD → -2 MD.",
  order_id: 145,
  person_name: "Paweł Łaski",
  person_names: ["Paweł Łaski"],
  changes: [{ label: "ręczna korekta MD", before: "0 MD", after: "-2 MD" }],
  balance_after: -19,
});

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <OrderHistoryPanel clientId={18} groupId={51} onFocusGroup={() => {}} />
    </QueryClientProvider>,
  );
}

describe("OrderHistoryPanel — historia zamówienia (ticket 7)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(orderGroupsApi.history).mockResolvedValue({
      data: {
        entries: [TEPER_SERIES, IMPORT, NEGATIVE, entry({ key: "ev-1" })],
        people: ["Konrad Teper", "Paweł Łaski"],
      },
    } as never);
  });

  it("wpis: data · autor · plakietka · osoba · „przed → po” · saldo po zmianie", async () => {
    renderPanel();
    const row = (await screen.findByText("Konrad Teper", { selector: "span" })).closest("li")!;
    expect(row).toHaveTextContent(/24\.09\.2026 \d{2}:\d{2}/);
    expect(row).toHaveTextContent("Anna Korycka");
    expect(row).toHaveTextContent("Edycja");
    expect(row).toHaveTextContent("stawka kosztowa: 560 zł/MD → 580 zł/MD");
    expect(row).toHaveTextContent("budżet MD: 9,66 MD → 10 MD");
    expect(row).toHaveTextContent("saldo po: 5,963 MD");
    expect(row).toHaveTextContent("(było -4)");
  });

  it("seria edycji to jeden wpis z rozwinięciem „▸ 6 zmian”", async () => {
    const user = userEvent.setup();
    renderPanel();
    const toggle = await screen.findByRole("button", { name: "6 zmian" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Zmiana nr 1")).toBeNull();
    await user.click(toggle);
    for (let i = 1; i <= 6; i += 1) {
      expect(screen.getByText(`Zmiana nr ${i}`)).toBeInTheDocument();
    }
  });

  it("import to jeden wpis z odsyłaczem „Otwórz import →” do zakładki Importy MD", async () => {
    renderPanel();
    const row = (await screen.findByText("Import MD za sierpień 2026 – 2 osoby, 25 MD")).closest("li")!;
    expect(within(row).getByRole("link", { name: "Otwórz import →" })).toHaveAttribute(
      "href",
      "/clients/18?tab=importy-md&import=2",
    );
  });

  it("ujemne saldo po zmianie jest czerwone", async () => {
    renderPanel();
    const row = (await screen.findByText("Paweł Łaski", { selector: "span.font-medium" })).closest("li")!;
    expect(within(row).getByText("-19 MD")).toHaveClass("text-destructive");
  });

  it("filtry: typ zdarzenia i osoba", async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByRole("button", { name: "6 zmian" });

    await user.selectOptions(screen.getByLabelText("Typ zdarzenia"), "consumption");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText(/Import MD za sierpień 2026/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Typ zdarzenia"), "all");
    await user.selectOptions(screen.getByLabelText("Osoba"), "Paweł Łaski");
    expect(screen.queryByRole("button", { name: "6 zmian" })).toBeNull();
    expect(screen.getByText(/Import MD za sierpień 2026/)).toBeInTheDocument();
    expect(screen.queryByText(/Utworzono zamówienie/)).toBeNull();

    await user.selectOptions(screen.getByLabelText("Typ zdarzenia"), "order");
    expect(screen.getByText("Żaden wpis nie pasuje do wybranych filtrów.")).toBeInTheDocument();
  });

  it("awaria pobrania to błąd z ponowieniem, nie pusta historia", async () => {
    vi.mocked(orderGroupsApi.history).mockRejectedValue(new Error("500"));
    renderPanel();
    expect(
      await screen.findByText("Nie udało się wczytać historii tego zamówienia."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Brak wpisów w historii.")).toBeNull();
  });
});
