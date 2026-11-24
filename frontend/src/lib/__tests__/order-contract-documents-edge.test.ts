import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  downloadContractDocument,
  fetchContractDocumentBlob,
  openContractDocument,
} from "@/lib/contract-documents";
import {
  downloadOrderDocument,
  fetchOrderDocumentBlob,
  openOrderDocument,
} from "@/lib/order-documents";

type FakeWin = { location: { href: string }; close: ReturnType<typeof vi.fn> };

let createObjectURL: ReturnType<typeof vi.fn>;
let revokeObjectURL: ReturnType<typeof vi.fn>;
let clicked: { href: string; download: string }[];

function mockFetchBlob(type: string, ok = true, status = 200) {
  const blob = new Blob(["%PDF"], { type });
  const fetchMock = vi.fn().mockResolvedValue({
    ok,
    status,
    blob: () => Promise.resolve(blob),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function fakeWindow(): FakeWin {
  return { location: { href: "" }, close: vi.fn() };
}

beforeEach(() => {
  createObjectURL = vi.fn(() => "blob:test-1");
  revokeObjectURL = vi.fn();
  Object.assign(URL, { createObjectURL, revokeObjectURL });
  clicked = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
    function (this: HTMLAnchorElement) {
      clicked.push({ href: this.getAttribute("href") ?? "", download: this.download });
    },
  );
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("fetch*DocumentBlob — odpowiedź z błędem", () => {
  it("dokument kontraktu: 401 rzuca „HTTP 401” i woła właściwy adres", async () => {
    const fetchMock = mockFetchBlob("application/pdf", false, 401);
    await expect(fetchContractDocumentBlob(7, 3)).rejects.toThrow("HTTP 401");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/contracts\/7\/documents\/3\/download$/);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "include" });
  });

  it("PO zamówienia: 404 rzuca „HTTP 404” i woła właściwy adres", async () => {
    const fetchMock = mockFetchBlob("application/pdf", false, 404);
    await expect(fetchOrderDocumentBlob(5, 9)).rejects.toThrow("HTTP 404");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/clients\/5\/orders\/9\/file$/);
  });
});

describe("openContractDocument", () => {
  it("PDF w otwartej karcie: karta dostaje blob URL, nic się nie pobiera", async () => {
    mockFetchBlob("application/pdf");
    const win = fakeWindow();
    vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    await openContractDocument(1, { id: 2, filename: "umowa.pdf", content_type: "application/pdf" });
    expect(win.location.href).toBe("blob:test-1");
    expect(win.close).not.toHaveBeenCalled();
    expect(clicked).toEqual([]);
    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(60_000);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:test-1");
  });

  it("HTML zadeklarowany przez wgrywającego: karta zamknięta, plik pobrany jako octet-stream", async () => {
    mockFetchBlob("text/html");
    const win = fakeWindow();
    vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    await openContractDocument(1, { id: 2, filename: "raport.html", content_type: "text/html" });
    expect(win.close).toHaveBeenCalled();
    expect(clicked).toEqual([{ href: "blob:test-1", download: "raport.html" }]);
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    expect(blob.type).toBe("application/octet-stream");
  });

  it("popup zablokowany przy PDF: pobiera zamiast otwierać", async () => {
    mockFetchBlob("application/pdf");
    vi.spyOn(window, "open").mockReturnValue(null);
    await openContractDocument(1, { id: 2, filename: "umowa.pdf" });
    expect(clicked).toEqual([{ href: "blob:test-1", download: "umowa.pdf" }]);
    // typ z odpowiedzi, gdy brak zadeklarowanego
    expect((createObjectURL.mock.calls[0][0] as Blob).type).toBe("application/pdf");
  });

  it("błąd pobrania zamyka otwartą kartę i rzuca dalej", async () => {
    mockFetchBlob("application/pdf", false, 500);
    const win = fakeWindow();
    vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    await expect(openContractDocument(1, { id: 2, filename: "umowa.pdf" })).rejects.toThrow("HTTP 500");
    expect(win.close).toHaveBeenCalled();
  });

  it("błąd pobrania przy zablokowanym popupie rzuca bez zamykania", async () => {
    mockFetchBlob("application/pdf", false, 403);
    vi.spyOn(window, "open").mockReturnValue(null);
    await expect(openContractDocument(1, { id: 2, filename: "umowa.pdf" })).rejects.toThrow("HTTP 403");
  });
});

describe("downloadContractDocument", () => {
  it("pobiera pod nazwą pliku i od razu zwalnia URL", async () => {
    mockFetchBlob("application/vnd.openxmlformats-officedocument.wordprocessingml.document");
    await downloadContractDocument(4, { id: 8, filename: "aneks.docx" });
    expect(clicked).toEqual([{ href: "blob:test-1", download: "aneks.docx" }]);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:test-1");
    expect(document.querySelectorAll("a[download]").length).toBe(0);
  });
});

describe("openOrderDocument", () => {
  const doc = { order_id: 12, client_id: 3, filename: "PO-12.pdf", content_type: "application/pdf" };

  it("PDF w otwartej karcie: karta dostaje blob URL", async () => {
    mockFetchBlob("application/pdf");
    const win = fakeWindow();
    vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    await openOrderDocument(doc);
    expect(win.location.href).toBe("blob:test-1");
    expect(clicked).toEqual([]);
    vi.advanceTimersByTime(60_000);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:test-1");
  });

  it("brak nazwy pliku i typ spoza listy: pobranie pod „zamowienie-<id>.pdf”", async () => {
    mockFetchBlob("");
    const win = fakeWindow();
    vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    await openOrderDocument({ ...doc, filename: null, content_type: null });
    expect(win.close).toHaveBeenCalled();
    expect(clicked).toEqual([{ href: "blob:test-1", download: "zamowienie-12.pdf" }]);
  });

  it("popup zablokowany: pobiera pod nazwą z PO", async () => {
    mockFetchBlob("application/pdf");
    vi.spyOn(window, "open").mockReturnValue(null);
    await openOrderDocument(doc);
    expect(clicked).toEqual([{ href: "blob:test-1", download: "PO-12.pdf" }]);
  });

  it("błąd pobrania zamyka kartę i rzuca", async () => {
    mockFetchBlob("application/pdf", false, 401);
    const win = fakeWindow();
    vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    await expect(openOrderDocument(doc)).rejects.toThrow("HTTP 401");
    expect(win.close).toHaveBeenCalled();
  });

  it("błąd przy zablokowanym popupie rzuca bez zamykania", async () => {
    mockFetchBlob("application/pdf", false, 502);
    vi.spyOn(window, "open").mockReturnValue(null);
    await expect(openOrderDocument(doc)).rejects.toThrow("HTTP 502");
  });
});

describe("downloadOrderDocument", () => {
  it("z nazwą: pobiera i zwalnia URL dopiero po 60 s", async () => {
    mockFetchBlob("application/pdf");
    await downloadOrderDocument({ order_id: 1, client_id: 2, filename: "PO.pdf", content_type: null });
    expect(clicked).toEqual([{ href: "blob:test-1", download: "PO.pdf" }]);
    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(60_000);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:test-1");
  });

  it("bez nazwy: domyślna „zamowienie-<id>.pdf”", async () => {
    mockFetchBlob("application/pdf");
    await downloadOrderDocument({ order_id: 77, client_id: 2, filename: null, content_type: null });
    expect(clicked).toEqual([{ href: "blob:test-1", download: "zamowienie-77.pdf" }]);
  });
});
