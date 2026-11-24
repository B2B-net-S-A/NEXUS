import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrderChangesTab } from "@/components/finance/OrderChangesTab";
import type {
  OrderChangesBoardState,
  OrderChangesSubTab,
} from "@/components/finance/OrderChangesPanel";
import type { ClientRef } from "@/components/clients/ClientSinglePicker";
import type { OrderChangesResponse, OrderPdfRef } from "@/lib/api/finance";
import { boardItems, type StatusFilter } from "@/lib/finance-order-board";
import type { MonthOption } from "@/lib/finance-order-changes";

/**
 * Logika zakładki „Zmiany w zamówieniach": miesiąc i filtry w adresie, stany
 * zapytania, odhaczanie „Zrobione”, pozycje faktury, pobrania i eksport.
 * Prezentację (`OrderChangesPanel`, `OrderChangesList`) sprawdza
 * `OrderChangesPanel.test.tsx` — tu zastępuje ją zaślepka, która oddaje props.
 */

interface PanelProps {
  data: OrderChangesResponse | null;
  body: ReactElement | null;
  subTab: OrderChangesSubTab;
  onSubTabChange: (next: OrderChangesSubTab) => void;
  month: string;
  months: MonthOption[];
  onMonthChange: (next: string) => void;
  onExport: () => void;
  exporting: boolean;
  filters: {
    search: string;
    onSearchChange: (value: string) => void;
    dateFrom: string;
    onDateFromChange: (value: string) => void;
    dateTo: string;
    onDateToChange: (value: string) => void;
    clientPicker: ReactElement<{ onChange: (next: ClientRef | null) => void }>;
    clientLabel: string | null;
    onClearClient: () => void;
    onClearDates: () => void;
    onClearAll: () => void;
  };
  status: StatusFilter;
  onStatusChange: (next: StatusFilter) => void;
  statusCounts: { todo: number; done: number; all: number } | null;
}

interface ListProps {
  data: OrderChangesResponse;
  subTab: OrderChangesSubTab;
  onOpenGaps: () => void;
  filtersActive: boolean;
  board: OrderChangesBoardState;
}

const captured = vi.hoisted(() => ({
  panel: null as unknown,
  list: null as unknown,
}));
const panel = () => captured.panel as PanelProps;
const list = () => captured.list as ListProps;

vi.mock("@/components/finance/OrderChangesPanel", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/components/finance/OrderChangesPanel")
  >()),
  OrderChangesPanel: (props: PanelProps) => {
    captured.panel = props;
    return <div data-testid="panel">{props.body}</div>;
  },
  OrderChangesList: (props: ListProps) => {
    captured.list = props;
    return <div data-testid="list">lista:{props.subTab}</div>;
  },
}));
vi.mock("@/components/clients/ClientSinglePicker", () => ({
  ClientSinglePicker: () => null,
}));
// Filtry idą od razu — zdławienie wpisywania nie jest przedmiotem tych testów.
vi.mock("@/lib/use-debounced-value", () => ({
  useDebouncedValue: <T,>(value: T) => value,
}));

const getOrderChanges = vi.fn();
const getOrderHistory = vi.fn();
const setOrderChangeCheck = vi.fn();
const updateInvoiceLine = vi.fn();
vi.mock("@/lib/api/finance", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/finance")>()),
  financeApi: {
    getOrderChanges: (...args: unknown[]) => getOrderChanges(...args),
    getOrderHistory: (...args: unknown[]) => getOrderHistory(...args),
    setOrderChangeCheck: (...args: unknown[]) => setOrderChangeCheck(...args),
    updateInvoiceLine: (...args: unknown[]) => updateInvoiceLine(...args),
  },
}));

const downloadAuthenticatedFile = vi.fn();
const fetchAuthenticatedBlob = vi.fn();
const downloadBlob = vi.fn();
vi.mock("@/lib/authenticated-files", () => ({
  downloadAuthenticatedFile: (...args: unknown[]) =>
    downloadAuthenticatedFile(...args),
  fetchAuthenticatedBlob: (...args: unknown[]) => fetchAuthenticatedBlob(...args),
  downloadBlob: (...args: unknown[]) => downloadBlob(...args),
}));

const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast }) }));

const PDF: OrderPdfRef = {
  kind: "order",
  id: 10,
  month: "2026-12",
  client_id: 2,
  download_name: "zam_Testowy.pdf",
};

const DATA: OrderChangesResponse = {
  period: { year: 2026, month: 12, label: "Grudzień 2026" },
  counts: { changes: 0, entries: 1, exits: 0, ending: 0, gaps: 0 },
  changes: [],
  entries: [
    {
      order_group_id: null,
      contract_id: 1,
      client_id: 2,
      client_name: "Firma Testowa sp. z o.o.",
      order_number: "Z-1",
      order_id: 10,
      consultant_name: "Jan Testowy",
      start_date: "2026-12-01",
      end_date: null,
      rate_cost: 100,
      rate_revenue: 130,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "periodic",
      status: "active",
      item_key: "entry:10",
      order_start: "2026-12-01",
      order_end: null,
      pdf: PDF,
      invoice_lines: [
        {
          index: 0,
          consultant: "Jan Testowy",
          text: "Usługi IT — grudzień",
          edited_by_name: null,
          edited_at: null,
        },
      ],
    },
  ],
  exits: [],
  ending_orders: [],
  gaps: [],
  changes_tracked_since: null,
  gaps_tracked_since: "2026-08-01",
  open_gaps_total: 0,
  can_check: true,
} as OrderChangesResponse;

let queryClient: QueryClient;

function renderTab(onOpenInPdfs?: (pdf: OrderPdfRef) => void) {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <OrderChangesTab onOpenInPdfs={onOpenInPdfs} />
    </QueryClientProvider>,
  );
}

const params = () => new URLSearchParams(window.location.search);
const entry = () => boardItems(DATA, "entries")[0];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  // 15 grudnia: lista miesięcy zaczyna się od stycznia NASTĘPNEGO roku.
  vi.setSystemTime(new Date("2026-12-15T10:00:00+01:00"));
  window.history.replaceState(null, "", "/finance?view=order-changes");
  getOrderChanges.mockResolvedValue({ data: DATA });
  getOrderHistory.mockResolvedValue({ data: { items: [] } });
  captured.panel = null;
  captured.list = null;
});

afterEach(() => {
  vi.useRealTimers();
  [
    getOrderChanges,
    getOrderHistory,
    setOrderChangeCheck,
    updateInvoiceLine,
    downloadAuthenticatedFile,
    fetchAuthenticatedBlob,
    downloadBlob,
    showToast,
  ].forEach((mock) => mock.mockReset());
  window.history.replaceState(null, "", "/finance");
});

describe("OrderChangesTab — miesiąc", () => {
  it("domyślnie bieżący miesiąc, choć lista zaczyna się od stycznia kolejnego roku", async () => {
    renderTab();
    await screen.findByTestId("list");
    expect(panel().months[0].value).toBe("2027-01");
    expect(panel().month).toBe("2026-12");
    expect(getOrderChanges).toHaveBeenCalledWith({
      year: 2026,
      month: 12,
      q: undefined,
      client_id: undefined,
      date_from: undefined,
      date_to: undefined,
    });
  });

  it("miesiąc z adresu spoza listy jest wybieralny z etykietą od serwera", async () => {
    window.history.replaceState(null, "", "/finance?month=2023-01");
    getOrderChanges.mockResolvedValue({
      data: { ...DATA, period: { year: 2023, month: 1, label: "Styczeń 2023" } },
    });
    renderTab();
    await screen.findByTestId("list");
    expect(getOrderChanges).toHaveBeenCalledWith(
      expect.objectContaining({ year: 2023, month: 1 }),
    );
    expect(panel().months.at(-1)).toEqual({
      value: "2023-01",
      year: 2023,
      month: 1,
      label: "Styczeń 2023",
    });
  });

  it("niepoprawny miesiąc w adresie (13.) to bieżący miesiąc", async () => {
    window.history.replaceState(null, "", "/finance?month=2026-13");
    renderTab();
    await screen.findByTestId("list");
    expect(panel().month).toBe("2026-12");
  });

  it("zmiana miesiąca trafia do adresu, a powrót na domyślny go usuwa", async () => {
    renderTab();
    await screen.findByTestId("list");

    act(() => panel().onMonthChange("2027-01"));
    expect(params().get("month")).toBe("2027-01");
    await waitFor(() =>
      expect(getOrderChanges).toHaveBeenLastCalledWith(
        expect.objectContaining({ year: 2027, month: 1 }),
      ),
    );

    act(() => panel().onMonthChange("2026-12"));
    expect(params().get("month")).toBeNull();
    expect(params().get("view")).toBe("order-changes");
  });
});

describe("OrderChangesTab — stany zapytania", () => {
  it("w trakcie wczytywania pokazuje komunikat, nie pustą listę", () => {
    getOrderChanges.mockReturnValue(new Promise(() => {}));
    renderTab();
    expect(
      screen.getByText("Wczytywanie zmian w zamówieniach…"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("list")).toBeNull();
  });

  it("awaria zapytania to komunikat błędu z ponowieniem, nie pusta lista", async () => {
    getOrderChanges.mockRejectedValueOnce(new Error("500"));
    renderTab();
    expect(
      await screen.findByText("Nie udało się wczytać zmian w zamówieniach."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("list")).toBeNull();
    expect(panel().data).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Spróbuj|Ponów/ }));
    expect(await screen.findByTestId("list")).toBeInTheDocument();
  });

  it("403 to „Brak uprawnień”, nie ogólny błąd", async () => {
    getOrderChanges.mockRejectedValue({ response: { status: 403 } });
    renderTab();
    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByTestId("list")).toBeNull();
  });

  it("padnięte odświeżenie w tle zostawia ostatnie dane z paskiem „Ponów”", async () => {
    renderTab();
    await screen.findByTestId("list");

    getOrderChanges.mockRejectedValueOnce(new Error("503"));
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: ["finance-order-changes"] });
    });

    expect(
      await screen.findByText(/Nie udało się odświeżyć danych/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("list")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    await waitFor(() =>
      expect(screen.queryByText(/Nie udało się odświeżyć danych/)).toBeNull(),
    );
  });

  it("odwrócony zakres dat nie pyta serwera i mówi, co poprawić", async () => {
    window.history.replaceState(
      null,
      "",
      "/finance?from=2026-12-20&to=2026-12-01",
    );
    renderTab();
    expect(
      screen.getByText(/Data „od" jest późniejsza niż „do"/),
    ).toBeInTheDocument();
    expect(getOrderChanges).not.toHaveBeenCalled();
    expect(screen.queryByText("Wczytywanie zmian w zamówieniach…")).toBeNull();
  });
});

describe("OrderChangesTab — filtry i adres", () => {
  it("odczytuje podzakładkę, status i kafelek klienta z adresu", async () => {
    window.history.replaceState(
      null,
      "",
      "/finance?sub=entries&status=done&tile=c:2",
    );
    renderTab();
    await screen.findByTestId("list");
    expect(panel().subTab).toBe("entries");
    expect(panel().status).toBe("done");
    expect(list().board.selectedClient).toBe("c:2");
  });

  it("nieznany status w adresie to „Do zrobienia”", async () => {
    window.history.replaceState(null, "", "/finance?status=wszystko");
    renderTab();
    await screen.findByTestId("list");
    expect(panel().status).toBe("todo");
  });

  it("klient z adresu bez nazwy dostaje zastępczą etykietę, niepoprawny id jest pomijany", async () => {
    window.history.replaceState(null, "", "/finance?client=5");
    const first = renderTab();
    await screen.findByTestId("list");
    expect(panel().filters.clientLabel).toBe("Klient #5");
    expect(getOrderChanges).toHaveBeenCalledWith(
      expect.objectContaining({ client_id: 5 }),
    );
    first.unmount();

    window.history.replaceState(null, "", "/finance?client=0");
    renderTab();
    await screen.findByTestId("list");
    expect(panel().filters.clientLabel).toBeNull();
  });

  it("wyszukiwanie, klient i daty idą do adresu i zapytania; „Wyczyść wszystko” je zdejmuje", async () => {
    renderTab();
    await screen.findByTestId("list");

    act(() => panel().filters.onSearchChange("  Testowy "));
    act(() =>
      panel().filters.clientPicker.props.onChange({
        id: 2,
        name: "Firma Testowa sp. z o.o.",
      }),
    );
    act(() => panel().filters.onDateFromChange("2026-12-01"));
    act(() => panel().filters.onDateToChange("2026-12-31"));

    expect(params().get("q")).toBe("  Testowy ");
    expect(params().get("client")).toBe("2");
    expect(params().get("clientName")).toBe("Firma Testowa sp. z o.o.");
    expect(params().get("from")).toBe("2026-12-01");
    expect(params().get("to")).toBe("2026-12-31");
    await waitFor(() =>
      expect(getOrderChanges).toHaveBeenLastCalledWith({
        year: 2026,
        month: 12,
        q: "Testowy",
        client_id: 2,
        date_from: "2026-12-01",
        date_to: "2026-12-31",
      }),
    );
    await waitFor(() => expect(list().filtersActive).toBe(true));

    act(() => panel().filters.onClearAll());
    for (const key of ["q", "client", "clientName", "from", "to"]) {
      expect(params().get(key)).toBeNull();
    }
    await waitFor(() => expect(list().filtersActive).toBe(false));
  });

  it("„Wyczyść klienta” i „Wyczyść daty” zdejmują tylko swoje filtry", async () => {
    window.history.replaceState(
      null,
      "",
      "/finance?client=2&clientName=Firma&from=2026-12-01&to=2026-12-31&q=Jan",
    );
    renderTab();
    await screen.findByTestId("list");

    act(() => panel().filters.onClearClient());
    expect(params().get("client")).toBeNull();
    expect(params().get("from")).toBe("2026-12-01");

    act(() => panel().filters.onClearDates());
    expect(params().get("from")).toBeNull();
    expect(params().get("to")).toBeNull();
    expect(params().get("q")).toBe("Jan");
  });

  it("podzakładka, status i kafelek klienta zapisują się w adresie; domyślne znikają", async () => {
    renderTab();
    await screen.findByTestId("list");

    act(() => panel().onSubTabChange("gaps"));
    act(() => panel().onStatusChange("all"));
    act(() => list().board.onSelectClient("c:2"));
    expect(params().get("sub")).toBe("gaps");
    expect(params().get("status")).toBe("all");
    expect(params().get("tile")).toBe("c:2");

    act(() => panel().onSubTabChange("changes"));
    act(() => panel().onStatusChange("todo"));
    // Typ panelu mówi `string`, ale zakładka przyjmuje też `null` (bez kafelka).
    act(() => list().board.onSelectClient(null as unknown as string));
    expect(params().get("sub")).toBeNull();
    expect(params().get("status")).toBeNull();
    expect(params().get("tile")).toBeNull();
  });

  it("„Przejdź do braków” z listy przełącza podzakładkę", async () => {
    renderTab();
    await screen.findByTestId("list");
    act(() => list().onOpenGaps());
    expect(panel().subTab).toBe("gaps");
    expect(params().get("sub")).toBe("gaps");
  });

  it("liczniki statusu liczą się z pozycji wybranej podzakładki", async () => {
    window.history.replaceState(null, "", "/finance?sub=entries");
    renderTab();
    await screen.findByTestId("list");
    expect(panel().statusCounts).toEqual({ todo: 1, done: 0, all: 1 });

    act(() => panel().onSubTabChange("gaps"));
    expect(panel().statusCounts).toEqual({ todo: 0, done: 0, all: 0 });
  });
});

describe("OrderChangesTab — „Zrobione”", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/finance?sub=entries");
  });

  it("zapisuje odhaczenie dla miesiąca i klucza pozycji, a dane zmieniają się od razu", async () => {
    const done = { by_name: "Anna Przykładowa", at: "2026-12-15T09:00:00Z" };
    setOrderChangeCheck.mockResolvedValue({ data: { item_key: "entry:10", done } });
    // Ponowny odczyt po zapisie oddaje już odhaczoną pozycję.
    getOrderChanges.mockResolvedValueOnce({ data: DATA }).mockResolvedValue({
      data: { ...DATA, entries: [{ ...DATA.entries[0], done }] },
    });
    renderTab();
    await screen.findByTestId("list");

    await act(async () => {
      await list().board.onToggle(entry(), true);
    });

    expect(setOrderChangeCheck).toHaveBeenCalledWith({
      year: 2026,
      month: 12,
      item_key: "entry:10",
      done: true,
    });
    await waitFor(() => expect(list().data.entries[0].done).toEqual(done));
    expect(list().board.pendingKeys.size).toBe(0);
    expect(showToast).not.toHaveBeenCalled();
  });

  it("drugie kliknięcie w trakcie zapisu nie wysyła drugiego żądania", async () => {
    let resolve: (value: unknown) => void = () => {};
    setOrderChangeCheck.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    renderTab();
    await screen.findByTestId("list");

    act(() => {
      void list().board.onToggle(entry(), true);
    });
    await waitFor(() => expect(list().board.pendingKeys.has("entry:10")).toBe(true));
    act(() => {
      void list().board.onToggle(entry(), true);
    });
    expect(setOrderChangeCheck).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolve({ data: { item_key: "entry:10", done: null } });
    });
    await waitFor(() => expect(list().board.pendingKeys.size).toBe(0));
  });

  it("błąd zapisu mówi o tym toastem i zwalnia pozycję", async () => {
    setOrderChangeCheck.mockRejectedValue(new Error("500"));
    renderTab();
    await screen.findByTestId("list");

    await act(async () => {
      await list().board.onToggle(entry(), false);
    });
    expect(showToast).toHaveBeenCalledWith(
      expect.stringContaining("Nie udało się zapisać „Zrobione”."),
      "error",
    );
    expect(list().board.pendingKeys.size).toBe(0);
  });
});

describe("OrderChangesTab — pozycja faktury", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/finance?sub=entries");
  });

  it("pozycja bez zamówienia (tylko grupa) nie wysyła zapisu", async () => {
    renderTab();
    await screen.findByTestId("list");
    let ok: boolean | undefined;
    await act(async () => {
      ok = await list().board.onSaveInvoiceLine!(
        { ...entry(), orderId: null },
        DATA.entries[0].invoice_lines![0],
        "Nowy tekst",
      );
    });
    expect(ok).toBe(false);
    expect(updateInvoiceLine).not.toHaveBeenCalled();
  });

  it("zapis podmienia tekst w karcie i potwierdza toastem", async () => {
    const saved = {
      ...DATA.entries[0].invoice_lines![0],
      text: "Usługi IT — grudzień 2026",
      edited_by_name: "Anna Przykładowa",
    };
    updateInvoiceLine.mockResolvedValue({
      data: { order_id: 10, lines: [saved] },
    });
    getOrderChanges.mockResolvedValueOnce({ data: DATA }).mockReturnValue(
      new Promise(() => {}),
    );
    renderTab();
    await screen.findByTestId("list");

    let ok: boolean | undefined;
    await act(async () => {
      ok = await list().board.onSaveInvoiceLine!(
        entry(),
        DATA.entries[0].invoice_lines![0],
        "Usługi IT — grudzień 2026",
      );
    });
    expect(ok).toBe(true);
    expect(updateInvoiceLine).toHaveBeenCalledWith(10, {
      index: 0,
      text: "Usługi IT — grudzień 2026",
    });
    expect(showToast).toHaveBeenCalledWith("Zapisano pozycję faktury.", "success");
    await waitFor(() =>
      expect(list().data.entries[0].invoice_lines![0].text).toBe(
        "Usługi IT — grudzień 2026",
      ),
    );
  });

  it("błąd zapisu zwraca false i pokazuje błąd", async () => {
    updateInvoiceLine.mockRejectedValue(new Error("422"));
    renderTab();
    await screen.findByTestId("list");
    let ok: boolean | undefined;
    await act(async () => {
      ok = await list().board.onSaveInvoiceLine!(
        entry(),
        DATA.entries[0].invoice_lines![0],
        "x",
      );
    });
    expect(ok).toBe(false);
    expect(showToast).toHaveBeenCalledWith(
      expect.stringContaining("Nie udało się zapisać pozycji faktury."),
      "error",
    );
  });
});

describe("OrderChangesTab — PDF, podgląd i eksport", () => {
  it("pobiera PDF zamówienia ścieżką pliku z nazwą od serwera", async () => {
    downloadAuthenticatedFile.mockResolvedValue(undefined);
    renderTab();
    await screen.findByTestId("list");
    await act(async () => {
      await list().board.onDownloadPdf(PDF);
    });
    expect(downloadAuthenticatedFile).toHaveBeenCalledWith(
      "/api/finance/order-pdfs/order/10/file",
      "zam_Testowy.pdf",
    );
    expect(list().board.downloadingPdf).toBeNull();
  });

  it("w trakcie pobierania drugi PDF nie startuje; błąd idzie toastem", async () => {
    let reject: (reason: unknown) => void = () => {};
    downloadAuthenticatedFile.mockReturnValue(
      new Promise((_, r) => {
        reject = r;
      }),
    );
    renderTab();
    await screen.findByTestId("list");
    act(() => {
      void list().board.onDownloadPdf(PDF);
    });
    await waitFor(() => expect(list().board.downloadingPdf).toBe("order:10"));
    act(() => {
      void list().board.onDownloadPdf({ ...PDF, id: 11 });
    });
    expect(downloadAuthenticatedFile).toHaveBeenCalledTimes(1);

    await act(async () => {
      reject(new Error("403"));
    });
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Nie udało się pobrać pliku.", "error"),
    );
    expect(list().board.downloadingPdf).toBeNull();
  });

  it("podgląd karty czyta historię zamówienia i oddaje pozycje karty", async () => {
    const history = [{ id: 1, kind: "rate", at: "2026-12-01T08:00:00Z" }];
    getOrderHistory.mockResolvedValue({ data: { items: history } });
    const onOpenInPdfs = vi.fn();
    renderTab(onOpenInPdfs);
    await screen.findByTestId("list");

    expect(list().board.preview.itemsForCard!("o:10")).toHaveLength(1);
    expect(getOrderHistory).not.toHaveBeenCalled();

    act(() => list().board.onPreviewCard("o:10"));
    await waitFor(() =>
      expect(getOrderHistory).toHaveBeenCalledWith({
        order_id: 10,
        order_group_id: null,
      }),
    );
    await waitFor(() =>
      expect(list().board.preview.history.items).toEqual(history),
    );

    list().board.preview.onOpenInPdfs(PDF);
    expect(onOpenInPdfs).toHaveBeenCalledWith(PDF);

    // Zmiana podzakładki zamyka podgląd.
    act(() => panel().onSubTabChange("exits"));
    expect(list().board.previewCard).toBeNull();
  });

  it("podgląd nieznanej karty nie pyta o historię", async () => {
    renderTab();
    await screen.findByTestId("list");
    act(() => list().board.onPreviewCard("o:999"));
    expect(list().board.previewCard).toBe("o:999");
    expect(getOrderHistory).not.toHaveBeenCalled();
  });

  it("eksport niesie podzakładkę i filtry ekranu, a nazwa pliku jest bez polskich znaków i spacji", async () => {
    window.history.replaceState(null, "", "/finance?sub=ending&q=Testowy&client=2");
    const blob = new Blob(["xlsx"]);
    fetchAuthenticatedBlob.mockResolvedValue(blob);
    renderTab();
    await screen.findByTestId("list");

    await act(async () => {
      await panel().onExport();
    });

    expect(fetchAuthenticatedBlob).toHaveBeenCalledWith(
      "/api/finance/order-changes/export?year=2026&month=12&tab=ending&q=Testowy&client_id=2",
    );
    expect(downloadBlob).toHaveBeenCalledWith(
      blob,
      "Zmiany_w_zamowieniach_Zamowienia_bez_kontynuacji_2026-12.xlsx",
    );
    expect(panel().exporting).toBe(false);
  });

  it("eksport Wejść w styczniu kolejnego roku nazywa plik miesiącem z ekranu", async () => {
    window.history.replaceState(null, "", "/finance?sub=entries&month=2027-01");
    fetchAuthenticatedBlob.mockResolvedValue(new Blob(["xlsx"]));
    renderTab();
    await screen.findByTestId("list");
    await act(async () => {
      await panel().onExport();
    });
    expect(downloadBlob).toHaveBeenCalledWith(
      expect.any(Blob),
      "Zmiany_w_zamowieniach_Wejscia_2027-01.xlsx",
    );
  });

  it("nieudany eksport mówi o tym toastem; w trakcie eksportu drugi nie startuje", async () => {
    let reject: (reason: unknown) => void = () => {};
    fetchAuthenticatedBlob.mockReturnValue(
      new Promise((_, r) => {
        reject = r;
      }),
    );
    renderTab();
    await screen.findByTestId("list");

    act(() => {
      void panel().onExport();
    });
    await waitFor(() => expect(panel().exporting).toBe(true));
    act(() => {
      void panel().onExport();
    });
    expect(fetchAuthenticatedBlob).toHaveBeenCalledTimes(1);

    await act(async () => {
      reject(new Error("500"));
    });
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        "Nie udało się pobrać eksportu.",
        "error",
      ),
    );
    expect(downloadBlob).not.toHaveBeenCalled();
    expect(panel().exporting).toBe(false);
  });
});
