import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";
import { mdConsumptionApi, orderGroupsApi } from "@/lib/api/orderGroups";

type Method = keyof typeof apiMock;

beforeEach(() => {
  for (const fn of Object.values(apiMock)) {
    fn.mockReset();
    fn.mockResolvedValue({ data: { ok: true } });
  }
});

const C = 11; // klient
const G = 22; // zamówienie
const L = 33; // linia
const base = `/api/clients/${C}/order-groups`;
const payload = { note: "Firma Testowa sp. z o.o." } as never;

/** Wywołanie, metoda HTTP i dokładne argumenty, z jakimi idzie do klienta HTTP. */
const cases: Array<[string, () => Promise<unknown>, Method, unknown[]]> = [
  ["lista zamówień klienta", () => orderGroupsApi.list(C), "get", [base]],
  ["nowe zamówienie", () => orderGroupsApi.create(C, payload), "post", [base, payload]],
  ["poprawka zamówienia", () => orderGroupsApi.update(C, G, payload), "patch", [`${base}/${G}`, payload]],
  ["usunięcie zamówienia", () => orderGroupsApi.remove(C, G), "delete", [`${base}/${G}`]],
  ["usunięcie linii", () => orderGroupsApi.removeLine(C, G, L), "delete", [`${base}/${G}/lines/${L}`]],
  ["zamknięcie", () => orderGroupsApi.close(C, G, payload), "post", [`${base}/${G}/close`, payload]],
  ["ponowne otwarcie z pustym ciałem", () => orderGroupsApi.reopen(C, G), "post", [`${base}/${G}/reopen`, {}]],
  ["anulowanie z powodem", () => orderGroupsApi.cancel(C, G, "Klient wycofał"), "post", [`${base}/${G}/cancel`, { reason: "Klient wycofał" }]],
  ["anulowanie bez powodu wysyła null", () => orderGroupsApi.cancel(C, G, null), "post", [`${base}/${G}/cancel`, { reason: null }]],
  ["przywrócenie anulowanego", () => orderGroupsApi.restore(C, G), "post", [`${base}/${G}/restore`, {}]],
  ["przedłużenie", () => orderGroupsApi.extend(C, G, payload), "post", [`${base}/${G}/extend`, payload]],
  ["usunięcie pliku", () => orderGroupsApi.deleteFile(C, G), "delete", [`${base}/${G}/file`]],
  ["podpowiedzi konsultantów z domyślnym limitem", () => orderGroupsApi.consultantOptions(C, ""), "get", [`${base}/consultant-options`, { params: { q: "", limit: 100 } }]],
  ["podpowiedzi konsultantów z limitem", () => orderGroupsApi.consultantOptions(C, "Anna", 5), "get", [`${base}/consultant-options`, { params: { q: "Anna", limit: 5 } }]],
  ["dodanie linii", () => orderGroupsApi.addLine(C, G, payload), "post", [`${base}/${G}/lines`, payload]],
  ["dodanie linii z PDF-a razem", () => orderGroupsApi.addLines(C, G, []), "post", [`${base}/${G}/lines/batch`, { lines: [] }]],
  ["„Zostaw jako historię”", () => orderGroupsApi.keepLineHistory(C, G, L), "post", [`${base}/${G}/lines/${L}/keep-history`]],
  ["poprawka linii", () => orderGroupsApi.updateLine(C, G, L, payload), "patch", [`${base}/${G}/lines/${L}`, payload]],
  ["zamiana konsultanta", () => orderGroupsApi.swapLine(C, G, L, payload), "post", [`${base}/${G}/lines/${L}/swap`, payload]],
  ["zejścia MD linii", () => orderGroupsApi.listConsumptions(C, G, L), "get", [`${base}/${G}/lines/${L}/consumptions`]],
  ["wpis MD za grudzień", () => orderGroupsApi.putConsumption(C, G, L, "2026-12", payload), "put", [`${base}/${G}/lines/${L}/consumptions/2026-12`, payload]],
  ["usunięcie wpisu MD za styczeń", () => orderGroupsApi.deleteConsumption(C, G, L, "2027-01"), "delete", [`${base}/${G}/lines/${L}/consumptions/2027-01`]],
  ["zużycie kosztowe", () => orderGroupsApi.listCostConsumptions(C, G, L), "get", [`${base}/${G}/lines/${L}/cost-consumptions`]],
  ["wpis kosztowy", () => orderGroupsApi.putCostConsumption(C, G, L, "2026-12", payload), "put", [`${base}/${G}/lines/${L}/cost-consumptions/2026-12`, payload]],
  ["usunięcie wpisu kosztowego", () => orderGroupsApi.deleteCostConsumption(C, G, L, "2027-01"), "delete", [`${base}/${G}/lines/${L}/cost-consumptions/2027-01`]],
  ["zejścia wspólnej puli", () => orderGroupsApi.listSharedMdConsumptions(C, G), "get", [`${base}/${G}/md-consumptions`]],
  ["wpis wspólnej puli", () => orderGroupsApi.putSharedMdConsumption(C, G, "2026-12", payload), "put", [`${base}/${G}/md-consumptions/2026-12`, payload]],
  ["usunięcie wpisu wspólnej puli", () => orderGroupsApi.deleteSharedMdConsumption(C, G, "2027-01"), "delete", [`${base}/${G}/md-consumptions/2027-01`]],
  ["wejście za konsultanta", () => orderGroupsApi.takeover(C, G, payload), "post", [`${base}/${G}/takeover`, payload]],
  ["decyzja po zakończeniu współpracy", () => orderGroupsApi.resolveOffboardingCase(C, G, 44, payload), "post", [`${base}/${G}/offboarding-cases/44/resolve`, payload]],
  ["zdarzenia", () => orderGroupsApi.events(C, G), "get", [`${base}/${G}/events`]],
  ["historia biznesowa", () => orderGroupsApi.history(C, G), "get", [`${base}/${G}/history`]],
  ["importy MD klienta", () => orderGroupsApi.listClientMdImports(C), "get", [`/api/clients/${C}/md-imports`]],
  ["import MD klienta", () => orderGroupsApi.getClientMdImport(C, 5), "get", [`/api/clients/${C}/md-imports/5`]],
  ["importy zużycia z domyślnym limitem", () => mdConsumptionApi.listImports(), "get", ["/api/md-consumption/imports", { params: { limit: 100 } }]],
  ["importy zużycia z limitem", () => mdConsumptionApi.listImports(10), "get", ["/api/md-consumption/imports", { params: { limit: 10 } }]],
  ["szczegóły importu", () => mdConsumptionApi.getImport(5), "get", ["/api/md-consumption/imports/5"]],
  ["przypisanie wiersza bez zgody na przekroczenie", () => mdConsumptionApi.assignRow(5, 6, 7), "post", ["/api/md-consumption/imports/5/rows/6/assign", { order_id: 7, confirm_overflow: false }]],
  ["przypisanie wiersza z przekroczeniem puli", () => mdConsumptionApi.assignRow(5, 6, 7, true), "post", ["/api/md-consumption/imports/5/rows/6/assign", { order_id: 7, confirm_overflow: true }]],
  ["Polkomtel: podgląd ponownego przeliczenia", () => mdConsumptionApi.reprocessPolkomtel(5), "post", ["/api/md-consumption/imports/5/reprocess-polkomtel", { apply: false }]],
  ["Polkomtel: zapis ponownego przeliczenia", () => mdConsumptionApi.reprocessPolkomtel(5, true), "post", ["/api/md-consumption/imports/5/reprocess-polkomtel", { apply: true }]],
];

describe("orderGroupsApi i mdConsumptionApi — trasy i ciała", () => {
  it.each(cases)("%s", async (_name, call, method, args) => {
    await expect(call()).resolves.toEqual({ data: { ok: true } });
    expect(apiMock[method]).toHaveBeenCalledTimes(1);
    expect(apiMock[method]).toHaveBeenCalledWith(...args);
    for (const other of Object.keys(apiMock) as Method[]) {
      if (other !== method) expect(apiMock[other]).not.toHaveBeenCalled();
    }
  });
});

describe("pliki zamówienia", () => {
  it("podmiana PDF-a: multipart pod polem `file`", async () => {
    const file = new File(["%PDF"], "zamowienie.pdf");
    await orderGroupsApi.replaceFile(C, G, file);
    const [url, form, config] = apiMock.put.mock.calls[0];
    expect(url).toBe(`${base}/${G}/file`);
    expect((form as FormData).get("file")).toBe(file);
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });
  });

  it("odczyt planu z PDF-a ma wydłużony limit czasu (model czyta cały dokument)", async () => {
    const file = new File(["%PDF"], "zamowienie.pdf");
    await orderGroupsApi.extractPlan(C, file);
    const [url, form, config] = apiMock.post.mock.calls[0];
    expect(url).toBe(`${base}/extract`);
    expect((form as FormData).get("file")).toBe(file);
    expect(config).toEqual({
      headers: { "Content-Type": "multipart/form-data" },
      timeout: SLOW_ENDPOINT_TIMEOUT_MS,
    });
    expect(SLOW_ENDPOINT_TIMEOUT_MS).toBeGreaterThan(30_000);
  });

  it("import zużycia MD: plik i miesiąc w formularzu", async () => {
    const file = new File(["x"], "zuzycie-2026-12.xlsx");
    await mdConsumptionApi.upload(file, "2026-12");
    const [url, form, config] = apiMock.post.mock.calls[0];
    expect(url).toBe("/api/md-consumption/imports");
    expect((form as FormData).get("file")).toBe(file);
    expect((form as FormData).get("period_month")).toBe("2026-12");
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });
  });
});

describe("błędy serwera", () => {
  it("409 przy anulowaniu zamówienia z rozliczeniami dochodzi do ekranu", async () => {
    const error = { response: { status: 409, data: { detail: { settled: ["2026-12"] } } } };
    apiMock.post.mockRejectedValueOnce(error);
    await expect(orderGroupsApi.cancel(C, G, null)).rejects.toBe(error);
  });

  it("403 przy zużyciu kosztowym dla roli bez finansów", async () => {
    const error = { response: { status: 403 } };
    apiMock.get.mockRejectedValueOnce(error);
    await expect(orderGroupsApi.listCostConsumptions(C, G, L)).rejects.toBe(error);
  });
});
