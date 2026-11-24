import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import {
  financeApi,
  orderChangesExportPath,
  orderPdfFilePath,
  orderPdfZipPath,
} from "@/lib/api/finance";

beforeEach(() => {
  for (const fn of Object.values(apiMock)) {
    fn.mockReset();
    fn.mockResolvedValue({ data: {} });
  }
});

describe("orderChangesExportPath", () => {
  it("bez opcji: cały audyt miesiąca", () => {
    expect(orderChangesExportPath(2026, 11)).toBe(
      "/api/finance/order-changes/export?year=2026&month=11",
    );
  });

  it("podzakładka i wszystkie filtry z ekranu, fraza przycięta i zakodowana", () => {
    expect(
      orderChangesExportPath(2026, 12, {
        tab: "exits",
        q: "  Anna Przykładowa & syn ",
        client_id: 0,
        date_from: "2026-12-01",
        date_to: "2027-01-31",
      }),
    ).toBe(
      "/api/finance/order-changes/export?year=2026&month=12&tab=exits" +
        "&q=Anna+Przyk%C5%82adowa+%26+syn&client_id=0&date_from=2026-12-01&date_to=2027-01-31",
    );
  });

  it("pomija pustą frazę, brak klienta i puste daty", () => {
    expect(
      orderChangesExportPath(2027, 1, {
        q: "   ",
        client_id: null,
        date_from: null,
        date_to: "",
      }),
    ).toBe("/api/finance/order-changes/export?year=2027&month=1");
  });
});

describe("orderPdfFilePath", () => {
  it("pobranie liczy się jako pobranie, podgląd nie", () => {
    expect(orderPdfFilePath({ kind: "group", id: 5 })).toBe(
      "/api/finance/order-pdfs/group/5/file",
    );
    expect(orderPdfFilePath({ kind: "amendment", id: 5 }, { preview: true })).toBe(
      "/api/finance/order-pdfs/amendment/5/file?preview=true",
    );
    expect(orderPdfFilePath({ kind: "order", id: 5 }, { preview: false })).toBe(
      "/api/finance/order-pdfs/order/5/file",
    );
  });
});

describe("orderPdfZipPath", () => {
  it("cały miesiąc bez klienta", () => {
    expect(orderPdfZipPath(2026, 12)).toBe("/api/finance/order-pdfs/zip?year=2026&month=12");
  });

  it("jeden klient, także o id 0; null to brak klienta", () => {
    expect(orderPdfZipPath(2026, 1, { clientId: 0 })).toBe(
      "/api/finance/order-pdfs/zip?year=2026&month=1&client_id=0",
    );
    expect(orderPdfZipPath(2026, 1, { clientId: null })).toBe(
      "/api/finance/order-pdfs/zip?year=2026&month=1",
    );
  });

  it("wskazane pliki jako `rodzaj:id` po przecinku", () => {
    expect(
      orderPdfZipPath(2026, 2, {
        clientId: 7,
        files: [
          { kind: "order", id: 1 },
          { kind: "amendment", id: 22 },
        ],
      }),
    ).toBe(
      "/api/finance/order-pdfs/zip?year=2026&month=2&client_id=7&files=order%3A1%2Camendment%3A22",
    );
  });

  it("pusta lista plików daje pusty parametr, nie znika", () => {
    expect(orderPdfZipPath(2026, 2, { files: [] })).toBe(
      "/api/finance/order-pdfs/zip?year=2026&month=2&files=",
    );
  });
});

describe("financeApi", () => {
  it("wyniki i okresy: parametry idą jako `params`", async () => {
    await financeApi.listPeriods();
    await financeApi.getResults({ year: 2026, month: 12, q: "Firma", sort: "margin", direction: "desc" });
    expect(apiMock.get.mock.calls).toEqual([
      ["/api/finance/periods"],
      [
        "/api/finance/results",
        { params: { year: 2026, month: 12, q: "Firma", sort: "margin", direction: "desc" } },
      ],
    ]);
  });

  it("poprawka wiersza przenosi zero i null (wyczyszczenie pola)", async () => {
    await financeApi.updateRow(9, { margin_pln: 0, md_count: null, cost_rate_md: -150.5 });
    expect(apiMock.patch).toHaveBeenCalledWith("/api/finance/results/9", {
      margin_pln: 0,
      md_count: null,
      cost_rate_md: -150.5,
    });
  });

  it("import arkusza: domyślnie bez zastąpienia, pola formularza jako tekst", async () => {
    const file = new File(["x"], "wyniki.xlsx");
    await financeApi.importWorkbook(file, 2026, 12);
    const [url, form, config] = apiMock.post.mock.calls[0];
    expect(url).toBe("/api/finance/imports");
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });
    const fd = form as FormData;
    expect(fd.get("file")).toBe(file);
    expect(fd.get("year")).toBe("2026");
    expect(fd.get("month")).toBe("12");
    expect(fd.get("replace")).toBe("false");
  });

  it("import po pytaniu o konflikt wysyła replace=true", async () => {
    await financeApi.importWorkbook(new File(["x"], "w.xlsx"), 2027, 1, true);
    expect((apiMock.post.mock.calls[0][1] as FormData).get("replace")).toBe("true");
  });

  it("409 przy istniejącej wersji miesiąca dochodzi do ekranu bez zmian", async () => {
    const conflict = { response: { status: 409, data: { detail: { rows_with_edits: 3 } } } };
    apiMock.post.mockRejectedValueOnce(conflict);
    await expect(
      financeApi.importWorkbook(new File(["x"], "w.xlsx"), 2026, 12),
    ).rejects.toBe(conflict);
  });

  it("historia importów i przywrócenie wersji", async () => {
    await financeApi.listImports();
    await financeApi.restoreImport(4);
    expect(apiMock.get).toHaveBeenCalledWith("/api/finance/imports");
    expect(apiMock.post).toHaveBeenCalledWith("/api/finance/imports/4/restore");
  });

  it("Zmiany w zamówieniach: lista, podsumowanie, odhaczenie, pozycja faktury, historia", async () => {
    await financeApi.getOrderChanges({ year: 2026, month: 12, q: "x", client_id: 3 });
    await financeApi.getOrderChangesSummary();
    await financeApi.setOrderChangeCheck({ year: 2026, month: 12, item_key: "rate_cost:1", done: false });
    await financeApi.updateInvoiceLine(15, { index: 0, text: "[brak]" });
    await financeApi.getOrderHistory({ order_id: null, order_group_id: 8 });

    expect(apiMock.get.mock.calls).toEqual([
      ["/api/finance/order-changes", { params: { year: 2026, month: 12, q: "x", client_id: 3 } }],
      ["/api/finance/order-changes/summary"],
      ["/api/finance/order-changes/history", { params: { order_id: null, order_group_id: 8 } }],
    ]);
    expect(apiMock.post).toHaveBeenCalledWith("/api/finance/order-changes/checks", {
      year: 2026,
      month: 12,
      item_key: "rate_cost:1",
      done: false,
    });
    expect(apiMock.put).toHaveBeenCalledWith("/api/finance/order-changes/invoice-lines/15", {
      index: 0,
      text: "[brak]",
    });
  });

  it("Zamówienia PDF: miesiące i pliki miesiąca", async () => {
    await financeApi.getOrderPdfMonths();
    await financeApi.getOrderPdfs({ year: 2027, month: 1 });
    expect(apiMock.get.mock.calls).toEqual([
      ["/api/finance/order-pdfs/months"],
      ["/api/finance/order-pdfs", { params: { year: 2027, month: 1 } }],
    ]);
  });
});
