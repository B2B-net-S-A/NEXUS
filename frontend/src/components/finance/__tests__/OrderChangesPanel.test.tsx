import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  OrderChangesList,
  OrderChangesPanel,
  type OrderChangesSubTab,
} from "@/components/finance/OrderChangesPanel";
import type { OrderChangesResponse } from "@/lib/api/finance";
import {
  boardItems,
  statusCounts,
  withCheck,
  type BoardItem,
  type StatusFilter,
} from "@/lib/finance-order-board";
import { monthOptions } from "@/lib/finance-order-changes";

// Podgląd PDF-u (pdf.js) nie jest przedmiotem tych testów.
vi.mock("@/components/v2/files/SearchablePdfPreview", () => ({
  SearchablePdfPreview: () => <div data-testid="pdf-preview" />,
}));

const ref = {
  order_group_id: null,
  contract_id: 1,
  client_id: 2,
  client_name: "Klient Demo",
  order_number: "NB-1",
};

const DATA: OrderChangesResponse = {
  period: { year: 2026, month: 9, label: "Wrzesień 2026" },
  counts: { changes: 0, entries: 1, exits: 1, ending: 1, gaps: 2 },
  changes: [],
  entries: [
    {
      ...ref,
      order_id: 10,
      consultant_name: "Jan Nowak",
      start_date: "2026-09-01",
      end_date: null,
      rate_cost: 120,
      rate_revenue: 152,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "periodic",
      status: "active",
      item_key: "entry:10",
      order_start: "2026-09-01",
      order_end: null,
      pdf: {
        kind: "order",
        id: 10,
        month: "2026-09",
        client_id: 2,
        download_name: "zam_Nowak.pdf",
      },
      entered_at: "2026-09-19T06:05:00Z",
      entered_by: null,
      entered_automatically: true,
      from_order_mail: true,
    },
  ],
  exits: [
    {
      ...ref,
      order_id: 12,
      consultant_name: "Olga Wiśniewska",
      end_date: "2026-09-15",
      start_date: "2026-01-01",
      rate_cost: 100,
      rate_revenue: 140,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "cost",
      verdict: "ended_intent",
      verdict_label: "Współpraca zakończona (umowa wypowiedziana)",
      intent: "contract_ended",
    },
  ],
  ending_orders: [
    {
      ...ref,
      order_id: 11,
      consultant_name: "Ewa Kowalska",
      end_date: "2026-09-05",
      start_date: "2026-01-01",
      rate_cost: 100,
      rate_revenue: 140,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "cost",
      verdict: "no_successor",
      verdict_label: "Zamówienie się skończyło, brak kolejnego — współpraca trwa",
      intent: null,
    },
  ],
  gaps: [
    {
      ...ref,
      order_id: 11,
      consultant_name: "Ewa Kowalska",
      gap_id: 1,
      ended_on: "2026-09-05",
      detected_on: "2026-09-06",
      status: "open",
      resolved_order_number: null,
      resolved_at: null,
      delay_days: null,
    },
    {
      ...ref,
      order_id: 12,
      consultant_name: "Kamil Nowicki",
      gap_id: 2,
      ended_on: "2026-08-31",
      detected_on: "2026-09-01",
      status: "filled_late",
      resolved_order_number: "NB-9",
      resolved_at: "2026-09-08T10:00:00Z",
      delay_days: 7,
    },
  ],
  changes_tracked_since: null,
  gaps_tracked_since: "2026-08-01",
  open_gaps_total: 1,
  can_check: true,
};

function Harness({
  data: initialData = DATA,
  initial = "entries",
  onExport = vi.fn(),
  filtersActive = false,
  onToggle,
  onOpenInPdfs = vi.fn(),
}: {
  data?: OrderChangesResponse | null;
  initial?: OrderChangesSubTab;
  onExport?: () => void;
  filtersActive?: boolean;
  onToggle?: (item: BoardItem, done: boolean) => void;
  onOpenInPdfs?: () => void;
}) {
  const [data, setData] = useState(initialData);
  const [subTab, setSubTab] = useState<OrderChangesSubTab>(initial);
  const [status, setStatus] = useState<StatusFilter>("todo");
  const [tile, setTile] = useState<string | null>(null);
  const [previewCard, setPreviewCard] = useState<string | null>(null);
  const [search, setSearch] = useState(filtersActive ? "kowalska" : "");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  return (
    <OrderChangesPanel
      data={data}
      body={
        data ? (
          <OrderChangesList
            data={data}
            subTab={subTab}
            onOpenGaps={() => setSubTab("gaps")}
            filtersActive={Boolean(search || dateFrom || dateTo)}
            board={{
              status,
              selectedClient: tile,
              onSelectClient: setTile,
              onToggle: (item, done) => {
                onToggle?.(item, done);
                setData((current) =>
                  current
                    ? withCheck(
                        current,
                        item.key,
                        done ? { by_name: "Anna Finanse", at: "2026-09-22T07:14:00Z" } : null,
                      )
                    : current,
                );
              },
              pendingKeys: new Set(),
              onDownloadPdf: vi.fn(),
              downloadingPdf: null,
              previewCard,
              onPreviewCard: setPreviewCard,
              preview: {
                history: { items: [], loading: false, failed: false },
                loadPdf: async () => new Blob(["%PDF"]),
                onOpenInPdfs,
              },
            }}
          />
        ) : (
          <p>Wczytywanie</p>
        )
      }
      subTab={subTab}
      onSubTabChange={setSubTab}
      month="2026-09"
      months={monthOptions(new Date(2026, 8, 14))}
      onMonthChange={vi.fn()}
      onExport={onExport}
      exporting={false}
      status={status}
      onStatusChange={setStatus}
      statusCounts={data ? statusCounts(boardItems(data, subTab)) : null}
      filters={{
        search,
        onSearchChange: setSearch,
        dateFrom,
        onDateFromChange: setDateFrom,
        dateTo,
        onDateToChange: setDateTo,
        clientPicker: <span data-testid="client-picker" />,
        clientLabel: null,
        onClearClient: vi.fn(),
        onClearDates: () => {
          setDateFrom("");
          setDateTo("");
        },
        onClearAll: () => {
          setSearch("");
          setDateFrom("");
          setDateTo("");
        },
      }}
    />
  );
}

describe("OrderChangesPanel", () => {
  it("shows the five sub-tabs with their counts", () => {
    render(<Harness />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Zmiany0",
      "Wejścia1",
      "Zejścia1",
      "Zamówienia bez kontynuacji1",
      "Braki2",
    ]);
  });

  it("does not claim zero before the data arrives", () => {
    render(<Harness data={null} />);
    expect(screen.getByRole("tab", { name: "Braki" }).textContent).toBe("Braki");
  });

  it("groups a sub-tab by client and order card, and points to open gaps", () => {
    render(<Harness />);
    expect(screen.getByRole("option", { name: /Klient Demo/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const card = screen.getByRole("button", {
      name: "Podgląd: Zam. NB-1 · 01.09.2026 – bezterminowo · Jan Nowak",
    });
    expect(within(card).getAllByText("Nowe zamówienie").length).toBeGreaterThan(0);
    expect(card.textContent).toContain("stawka przychodowa 152,00 zł/h");
    expect(card.textContent).toContain(
      "dodane automatycznie (zamowienia@b2bnetwork.pl)",
    );

    fireEvent.click(screen.getByRole("button", { name: "sprawdź podzakładkę Braki" }));
    expect(screen.getAllByText("Brak zamówienia").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Uzupełnione z opóźnieniem: zam\. NB-9 \(7 dni po terminie\)/),
    ).toBeInTheDocument();
  });

  it("checks one change, records who did it and moves a finished card to „Zrobione”", () => {
    const onToggle = vi.fn();
    render(<Harness onToggle={onToggle} />);
    expect(screen.getByRole("radio", { name: "Do zrobienia · 1" })).toBeChecked();
    expect(screen.getByLabelText("Zrobione we wrześniu: 0 z 1")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("checkbox", { name: /Oznacz jako zrobione: Nowe zamówienie/ }),
    );
    expect(onToggle).toHaveBeenCalledWith(
      expect.objectContaining({ key: "entry:10" }),
      true,
    );
    expect(screen.getByRole("radio", { name: "Zrobione · 1" })).toBeInTheDocument();
    expect(screen.getByLabelText("Zrobione we wrześniu: 1 z 1")).toBeInTheDocument();
    // Karta w całości zrobiona: zwinięta sekcja „Zrobione (1)”.
    const section = screen.getByRole("button", { name: /Zrobione \(1\)/ });
    expect(section).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(section);
    expect(screen.getByText(/Zrobione: Anna Finanse · 22\.09\.2026/)).toBeInTheDocument();
  });

  it("stays on the client after its last change is checked", () => {
    const other = {
      ...DATA.entries[0],
      order_id: 30,
      client_id: 99,
      client_name: "Inny Klient",
      consultant_name: "Zofia Inna",
      item_key: "entry:30",
    };
    const data = {
      ...DATA,
      entries: [DATA.entries[0], other, { ...other, order_id: 31, item_key: "entry:31" }],
    };
    render(<Harness data={data} />);
    // Domyślnie wybrany jest klient z największą liczbą pozycji do zrobienia.
    const first = within(screen.getByRole("listbox", { name: "Klienci" })).getAllByRole(
      "option",
    )[0];
    expect(first).toHaveTextContent("Inny Klient");
    fireEvent.click(
      screen.getAllByRole("checkbox", { name: /Oznacz jako zrobione/ })[0],
    );
    fireEvent.click(
      screen.getAllByRole("checkbox", { name: /Oznacz jako zrobione/ })[0],
    );
    // Kafelek spadł na dół listy, ale widok został przy tym kliencie.
    expect(screen.getByRole("option", { name: /Inny Klient/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("region", { name: "Zamówienia — Inny Klient" })).toBeInTheDocument();
  });

  it("opens the preview panel from the card, switches cards and closes on Esc", async () => {
    const onOpenInPdfs = vi.fn();
    render(<Harness onOpenInPdfs={onOpenInPdfs} />);
    expect(screen.queryByRole("complementary", { name: "Podgląd zamówienia" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Podgląd PDF: zamówienie NB-1" }));
    const panel = screen.getByRole("complementary", { name: "Podgląd zamówienia" });
    expect(await within(panel).findByTestId("pdf-preview")).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: /Otwórz w Zamówienia PDF/ }));
    expect(onOpenInPdfs).toHaveBeenCalledWith(expect.objectContaining({ month: "2026-09" }));

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("complementary", { name: "Podgląd zamówienia" })).toBeNull();
  });

  it("warns about a change without a PDF and disables its download", () => {
    render(<Harness initial="exits" />);
    expect(
      screen.getByText("Brak PDF – zmiana wprowadzona ręcznie"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pobierz PDF: zamówienie/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Podgląd: Zam\. NB-1/ }));
    const panel = screen.getByRole("complementary", { name: "Podgląd zamówienia" });
    expect(within(panel).getByRole("button", { name: "Pobierz PDF" })).toBeDisabled();
    // Bez PDF-u zmianę nadal da się odhaczyć.
    expect(
      within(panel).getByRole("checkbox", { name: /Oznacz jako zrobione: Zejście/ }),
    ).toBeEnabled();
  });

  it("tells finance that change history starts with the deployment", () => {
    render(<Harness initial="changes" />);
    expect(screen.getByText(/Dziennik zmian stawek i dat działa od wdrożenia/)).toBeInTheDocument();
  });

  it("names the date filter after the active sub-tab", () => {
    render(<Harness initial="entries" />);
    expect(screen.getByLabelText("Data wejścia od")).toBeInTheDocument();

    // Radix aktywuje zakładkę na `mousedown`, nie na `click`.
    fireEvent.mouseDown(screen.getByRole("tab", { name: /Zejścia/ }));
    expect(screen.getByLabelText("Data zejścia od")).toBeInTheDocument();
    expect(screen.queryByLabelText("Data wejścia od")).not.toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("tab", { name: /Zamówienia bez kontynuacji/ }));
    expect(screen.getByLabelText("Data końca zamówienia od")).toBeInTheDocument();
  });

  it("keeps a person whose order merely ends out of the exits tab", () => {
    // Zejście = zapisany koniec współpracy. Zamówienie bez kontynuacji to inne
    // pytanie i inna zakładka — ta sama osoba nie może stać w obu.
    render(<Harness initial="exits" />);
    expect(screen.getByText(/Olga Wiśniewska/)).toBeInTheDocument();
    expect(screen.queryByText(/Ewa Kowalska/)).not.toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("tab", { name: /Zamówienia bez kontynuacji/ }));
    expect(screen.getByText(/Ewa Kowalska/)).toBeInTheDocument();
    expect(screen.queryByText(/Olga Wiśniewska/)).not.toBeInTheDocument();
  });

  it("sends an empty exits tab to the tab that does hold those rows", () => {
    const empty = { ...DATA, exits: [], counts: { ...DATA.counts, exits: 0 } };
    render(<Harness data={empty} initial="exits" />);
    expect(
      screen.getByText(/są w zakładce\s+Zamówienia bez kontynuacji/),
    ).toBeInTheDocument();
  });

  it("exports the sub-tab the user is looking at", () => {
    const onExport = vi.fn();
    render(<Harness initial="gaps" onExport={onExport} />);

    const button = screen.getByRole("button", { name: "Eksport do Excela: Braki" });
    fireEvent.click(button);
    expect(onExport).toHaveBeenCalledTimes(1);
  });

  it("shows an active filter as a removable chip", () => {
    render(<Harness filtersActive />);
    const chip = screen.getByText("Szukaj: kowalska");
    expect(chip).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Usuń filtr: Szukaj: kowalska" }));
    expect(screen.queryByText("Szukaj: kowalska")).not.toBeInTheDocument();
  });

  it("clears both dates in one call, so the URL cannot keep a stale bound", () => {
    const onClearDates = vi.fn();
    render(
      <OrderChangesPanel
        data={DATA}
        body={null}
        subTab="changes"
        onSubTabChange={vi.fn()}
        month="2026-09"
        months={monthOptions(new Date(2026, 8, 14))}
        onMonthChange={vi.fn()}
        onExport={vi.fn()}
        exporting={false}
        filters={{
          search: "",
          onSearchChange: vi.fn(),
          dateFrom: "2026-09-01",
          onDateFromChange: vi.fn(),
          dateTo: "2026-09-30",
          onDateToChange: vi.fn(),
          clientPicker: null,
          clientLabel: null,
          onClearClient: vi.fn(),
          onClearDates,
          onClearAll: vi.fn(),
        }}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Usuń filtr: Data zmiany: od 01.09.2026 do 30.09.2026",
      }),
    );
    expect(onClearDates).toHaveBeenCalledTimes(1);
  });

  it("says a filter hid the rows instead of claiming the month was empty", () => {
    const empty = { ...DATA, entries: [], counts: { ...DATA.counts, entries: 0 } };
    render(<Harness data={empty} filtersActive />);
    expect(
      screen.getByText("Żaden wiersz nie pasuje do ustawionych filtrów."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Nikt nie rozpoczął z nami współpracy/)).toBeNull();
  });
});
