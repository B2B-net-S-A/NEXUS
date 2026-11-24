import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  OrderPdfsTab,
  defaultOrderPdfMonth,
} from "@/components/finance/OrderPdfsTab";
import type { OrderPdfClient, OrderPdfFile } from "@/lib/api/finance";

const getOrderPdfMonths = vi.fn();
const getOrderPdfs = vi.fn();
const showToast = vi.fn();
const downloadAuthenticatedFile = vi.fn();
const fetchAuthenticatedDownload = vi.fn();
const downloadBlob = vi.fn();

vi.mock("@/lib/api/finance", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/finance")>()),
  financeApi: {
    getOrderPdfMonths: (...args: unknown[]) => getOrderPdfMonths(...args),
    getOrderPdfs: (...args: unknown[]) => getOrderPdfs(...args),
  },
}));
vi.mock("@/lib/authenticated-files", () => ({
  downloadAuthenticatedFile: (...args: unknown[]) =>
    downloadAuthenticatedFile(...args),
  fetchAuthenticatedDownload: (...args: unknown[]) =>
    fetchAuthenticatedDownload(...args),
  downloadBlob: (...args: unknown[]) => downloadBlob(...args),
  fetchAuthenticatedBlob: vi.fn(),
}));
vi.mock("@/components/finance/OrderPdfViewer", () => ({
  OrderPdfViewer: () => <div data-testid="pdf-viewer" />,
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast }) }));

function file(overrides: Partial<OrderPdfFile> = {}): OrderPdfFile {
  return {
    kind: "order",
    id: 1,
    download_name: "Firma_Testowa_Z1_Testowy_Nowe_01.12.2026-31.12.2026.pdf",
    original_name: "zamowienie.pdf",
    consultant_name: "Jan Testowy",
    start: "2026-12-01",
    end: "2026-12-31",
    entry_type: "new",
    status: "active",
    order_number: "Z1",
    uploaded_at: "2026-11-20T10:00:00Z",
    downloaded_at: null,
    ...overrides,
  };
}

const CLIENT: OrderPdfClient = {
  client_id: 42,
  client_name: "Firma Testowa sp. z o.o.",
  files: [
    file(),
    file({
      kind: "group",
      id: 2,
      download_name: "Firma_Testowa_Z2_Przykladowa_Aneks.pdf",
      consultant_name: "Anna Przykładowa",
      entry_type: "amendment",
      order_number: "Z2",
      downloaded_at: "2026-11-21T09:00:00Z",
    }),
  ],
};

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <OrderPdfsTab />
    </QueryClientProvider>,
  );
}

function months(items: { month: string; clients: number; files: number }[]) {
  getOrderPdfMonths.mockResolvedValue({ data: { items } });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-12-10T12:00:00+01:00"));
});

afterEach(() => {
  vi.useRealTimers();
  window.history.replaceState(null, "", "/finance");
  [
    getOrderPdfMonths,
    getOrderPdfs,
    showToast,
    downloadAuthenticatedFile,
    fetchAuthenticatedDownload,
    downloadBlob,
  ].forEach((mock) => mock.mockReset());
});

describe("defaultOrderPdfMonth", () => {
  const today = new Date(2026, 11, 10); // 10 grudnia 2026

  it("bez miesięcy nie ma domyślnego", () => {
    expect(defaultOrderPdfMonth([], today)).toBeNull();
  });

  it("bieżący miesiąc, gdy ma pliki", () => {
    expect(
      defaultOrderPdfMonth(
        [
          { month: "2027-01", clients: 1, files: 1 },
          { month: "2026-12", clients: 1, files: 2 },
          { month: "2026-11", clients: 1, files: 1 },
        ],
        today,
      ),
    ).toBe("2026-12");
  });

  it("bez bieżącego — najnowszy wcześniejszy, nie przyszły", () => {
    expect(
      defaultOrderPdfMonth(
        [
          { month: "2027-02", clients: 1, files: 1 },
          { month: "2026-10", clients: 1, files: 1 },
        ],
        today,
      ),
    ).toBe("2026-10");
  });

  it("granica roku: 5 stycznia wybiera grudzień poprzedniego roku", () => {
    expect(
      defaultOrderPdfMonth(
        [
          { month: "2027-02", clients: 1, files: 1 },
          { month: "2026-12", clients: 1, files: 1 },
        ],
        new Date(2027, 0, 5),
      ),
    ).toBe("2026-12");
  });

  it("same przyszłe miesiące — najbliższy z nich", () => {
    expect(
      defaultOrderPdfMonth(
        [
          { month: "2027-03", clients: 1, files: 1 },
          { month: "2027-01", clients: 1, files: 1 },
        ],
        today,
      ),
    ).toBe("2027-01");
  });
});

describe("OrderPdfsTab — miesiąc i klient", () => {
  it("bez zamówień z PDF-em pokazuje pusty stan i nie pyta o klientów", async () => {
    months([]);
    renderTab();
    expect(
      await screen.findByText("Brak zamówień z PDF-em w systemie."),
    ).toBeInTheDocument();
    expect(screen.getByText("Wybierz miesiąc.")).toBeInTheDocument();
    expect(getOrderPdfs).not.toHaveBeenCalled();
  });

  it("w trakcie ładowania miesięcy pokazuje „Ładowanie…”, nie pustą listę", () => {
    getOrderPdfMonths.mockReturnValue(new Promise(() => {}));
    renderTab();
    expect(screen.getByText("Ładowanie…")).toBeInTheDocument();
    expect(screen.queryByText("Brak zamówień z PDF-em w systemie.")).toBeNull();
  });

  it("pyta o bieżący miesiąc i pokazuje klientów z liczbą nowych plików", async () => {
    months([{ month: "2026-12", clients: 1, files: 2 }]);
    getOrderPdfs.mockResolvedValue({
      data: { year: 2026, month: 12, clients: [CLIENT] },
    });
    renderTab();

    expect(await screen.findByText("Firma Testowa sp. z o.o.")).toBeInTheDocument();
    expect(getOrderPdfs).toHaveBeenCalledWith({ year: 2026, month: 12 });
    expect(screen.getByText("1 nowy")).toBeInTheDocument();
    expect(screen.getByText("1 klient · 2 pliki")).toBeInTheDocument();
    expect(
      screen.getByText("Wybierz klienta, aby zobaczyć PDF-y."),
    ).toBeInTheDocument();
  });

  it("miesiąc z adresu spoza listy jest pozycją z zerem, a ZIP miesiąca jest wyłączony", async () => {
    window.history.replaceState(null, "", "/finance?view=order-pdfs&pdfMonth=2027-01");
    months([{ month: "2026-12", clients: 1, files: 2 }]);
    getOrderPdfs.mockResolvedValue({ data: { year: 2027, month: 1, clients: [] } });
    renderTab();

    expect(await screen.findByText("0 klientów · 0 plików")).toBeInTheDocument();
    expect(getOrderPdfs).toHaveBeenCalledWith({ year: 2027, month: 1 });
    const options = within(
      screen.getByRole("listbox", { name: "Miesiąc rozpoczęcia" }),
    ).getAllByRole("option");
    // Posortowane malejąco: styczeń 2027 przed grudniem 2026.
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(options[0]).toHaveTextContent("Styczeń 2027");
    expect(
      screen.getByRole("button", { name: /Pobierz cały miesiąc/ }),
    ).toBeDisabled();
    expect(
      await screen.findByText(
        "W tym miesiącu nie zaczyna się żadne zamówienie z PDF-em.",
      ),
    ).toBeInTheDocument();
  });

  it("niepoprawny miesiąc i klient w adresie są ignorowane", async () => {
    window.history.replaceState(null, "", "/finance?pdfMonth=2026-13&pdfClient=-1");
    months([{ month: "2026-12", clients: 1, files: 2 }]);
    getOrderPdfs.mockResolvedValue({
      data: { year: 2026, month: 12, clients: [CLIENT] },
    });
    renderTab();
    expect(await screen.findByText("Firma Testowa sp. z o.o.")).toBeInTheDocument();
    expect(getOrderPdfs).toHaveBeenCalledWith({ year: 2026, month: 12 });
    expect(
      screen.getByText("Wybierz klienta, aby zobaczyć PDF-y."),
    ).toBeInTheDocument();
  });

  it("błąd listy klientów to komunikat z ponowieniem, nie „brak zamówień”", async () => {
    months([{ month: "2026-12", clients: 1, files: 2 }]);
    getOrderPdfs.mockRejectedValueOnce(new Error("503"));
    renderTab();
    expect(
      await screen.findByText("Nie udało się pobrać danych"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("W tym miesiącu nie zaczyna się żadne zamówienie z PDF-em."),
    ).toBeNull();

    getOrderPdfs.mockResolvedValue({
      data: { year: 2026, month: 12, clients: [CLIENT] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Spróbuj ponownie|Ponów/ }));
    expect(await screen.findByText("Firma Testowa sp. z o.o.")).toBeInTheDocument();
  });

  it("wybór klienta zapisuje go w adresie, zmiana miesiąca go czyści", async () => {
    months([
      { month: "2026-12", clients: 1, files: 2 },
      { month: "2026-11", clients: 1, files: 1 },
    ]);
    getOrderPdfs.mockResolvedValue({
      data: { year: 2026, month: 12, clients: [CLIENT] },
    });
    renderTab();

    fireEvent.click(await screen.findByRole("option", { name: /Firma Testowa/ }));
    expect(new URLSearchParams(window.location.search).get("pdfClient")).toBe("42");
    expect(
      screen.getByRole("heading", {
        name: "Firma Testowa sp. z o.o. — Grudzień 2026",
      }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("option", { name: /Listopad 2026/ }));
    const params = new URLSearchParams(window.location.search);
    expect(params.get("pdfMonth")).toBe("2026-11");
    expect(params.get("pdfClient")).toBeNull();
    await waitFor(() =>
      expect(getOrderPdfs).toHaveBeenLastCalledWith({ year: 2026, month: 11 }),
    );
  });
});

describe("OrderPdfsTab — pobieranie", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/finance?pdfMonth=2026-12&pdfClient=42");
    months([{ month: "2026-12", clients: 1, files: 2 }]);
    getOrderPdfs.mockResolvedValue({
      data: { year: 2026, month: 12, clients: [CLIENT] },
    });
  });

  it("pojedynczy plik idzie ścieżką pliku z nazwą od serwera i odświeża statusy", async () => {
    downloadAuthenticatedFile.mockResolvedValue(undefined);
    renderTab();
    fireEvent.click(
      await screen.findByRole("button", {
        name: `Pobierz ${CLIENT.files[0].download_name}`,
      }),
    );
    await waitFor(() =>
      expect(downloadAuthenticatedFile).toHaveBeenCalledWith(
        "/api/finance/order-pdfs/order/1/file",
        CLIENT.files[0].download_name,
      ),
    );
    await waitFor(() => expect(getOrderPdfs).toHaveBeenCalledTimes(2));
    expect(showToast).not.toHaveBeenCalled();
  });

  it("nieudane pobranie pliku mówi o tym toastem", async () => {
    downloadAuthenticatedFile.mockRejectedValue(new Error("403"));
    renderTab();
    fireEvent.click(
      await screen.findByRole("button", {
        name: `Pobierz ${CLIENT.files[1].download_name}`,
      }),
    );
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Nie udało się pobrać pliku.", "error"),
    );
  });

  it("ZIP całego miesiąca bez nazwy od serwera dostaje nazwę awaryjną", async () => {
    const blob = new Blob(["zip"]);
    fetchAuthenticatedDownload.mockResolvedValue({ blob, filename: null });
    renderTab();
    fireEvent.click(
      await screen.findByRole("button", { name: /Pobierz cały miesiąc/ }),
    );
    await waitFor(() =>
      expect(downloadBlob).toHaveBeenCalledWith(blob, "Zamowienia_2026-12.zip"),
    );
    expect(fetchAuthenticatedDownload).toHaveBeenCalledWith(
      "/api/finance/order-pdfs/zip?year=2026&month=12",
    );
  });

  it("ZIP klienta niesie client_id, a nazwa od serwera wygrywa", async () => {
    const blob = new Blob(["zip"]);
    fetchAuthenticatedDownload.mockResolvedValue({
      blob,
      filename: "Firma_Testowa_2026-12.zip",
    });
    renderTab();
    fireEvent.click(
      await screen.findByRole("button", { name: "Pobierz wszystkie (ZIP)" }),
    );
    await waitFor(() =>
      expect(downloadBlob).toHaveBeenCalledWith(blob, "Firma_Testowa_2026-12.zip"),
    );
    expect(fetchAuthenticatedDownload).toHaveBeenCalledWith(
      "/api/finance/order-pdfs/zip?year=2026&month=12&client_id=42",
    );
  });

  it("ZIP klienta bez nazwy od serwera — nazwa z klienta bez polskich znaków", async () => {
    const blob = new Blob(["zip"]);
    fetchAuthenticatedDownload.mockResolvedValue({ blob, filename: null });
    renderTab();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Pobierz wszystkie pliki klienta: Firma Testowa sp. z o.o.",
      }),
    );
    await waitFor(() =>
      expect(downloadBlob).toHaveBeenCalledWith(
        blob,
        "Firma_Testowa_sp._z_o.o_2026-12.zip",
      ),
    );
  });

  it("„Pobierz nowe” pakuje tylko pliki niepobrane przez zalogowaną osobę", async () => {
    fetchAuthenticatedDownload.mockResolvedValue({
      blob: new Blob(["zip"]),
      filename: "x.zip",
    });
    renderTab();
    fireEvent.click(await screen.findByRole("button", { name: "Pobierz nowe (1)" }));
    await waitFor(() =>
      expect(fetchAuthenticatedDownload).toHaveBeenCalledWith(
        "/api/finance/order-pdfs/zip?year=2026&month=12&client_id=42&files=order%3A1",
      ),
    );
  });

  it("„Pobierz zaznaczone” jest wyłączone bez zaznaczenia i pakuje zaznaczony plik", async () => {
    fetchAuthenticatedDownload.mockResolvedValue({
      blob: new Blob(["zip"]),
      filename: "x.zip",
    });
    renderTab();
    const button = await screen.findByRole("button", {
      name: "Pobierz zaznaczone (0)",
    });
    expect(button).toBeDisabled();

    fireEvent.click(
      screen.getByRole("checkbox", { name: "Zaznacz: Zam. Z2 · Anna Przykładowa" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Pobierz zaznaczone (1)" }));
    await waitFor(() =>
      expect(fetchAuthenticatedDownload).toHaveBeenCalledWith(
        "/api/finance/order-pdfs/zip?year=2026&month=12&client_id=42&files=group%3A2",
      ),
    );
  });

  it("w trakcie budowy ZIP-a pozostałe przyciski ZIP są wyłączone", async () => {
    fetchAuthenticatedDownload.mockReturnValue(new Promise(() => {}));
    renderTab();
    fireEvent.click(
      await screen.findByRole("button", { name: /Pobierz cały miesiąc/ }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Pobierz wszystkie (ZIP)" }),
      ).toBeDisabled(),
    );
    expect(screen.getByRole("button", { name: "Pobierz nowe (1)" })).toBeDisabled();
    // Drugie kliknięcie nie buduje drugiego archiwum.
    fireEvent.click(screen.getByRole("button", { name: /Pobierz cały miesiąc/ }));
    expect(fetchAuthenticatedDownload).toHaveBeenCalledTimes(1);
  });

  it("błąd ZIP-a bez treści od serwera pokazuje komunikat domyślny", async () => {
    fetchAuthenticatedDownload.mockRejectedValue(new Error("network"));
    renderTab();
    fireEvent.click(
      await screen.findByRole("button", { name: "Pobierz wszystkie (ZIP)" }),
    );
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        expect.stringContaining("Nie udało się pobrać archiwum ZIP."),
        "error",
      ),
    );
    expect(downloadBlob).not.toHaveBeenCalled();
  });

  it("błąd ZIP-a z `detail` od serwera pokazuje jego treść", async () => {
    fetchAuthenticatedDownload.mockRejectedValue({
      response: { status: 404, data: { detail: "Brak plików w tym miesiącu." } },
    });
    renderTab();
    fireEvent.click(
      await screen.findByRole("button", { name: /Pobierz cały miesiąc/ }),
    );
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        expect.stringContaining("Brak plików w tym miesiącu."),
        "error",
      ),
    );
  });
});
